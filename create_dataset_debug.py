import math
import glob
import os
import sys
from osgeo import gdal
from osgeo import gdalconst
from osgeo import osr
from qgis.utils import iface
from qgis.core import QgsProject
from qgis.core import QgsApplication
from time import sleep
import multiprocessing
import concurrent.futures
from itertools import repeat
from datetime import datetime
import threading
from lxml import etree
from difflib import SequenceMatcher
import random
import traceback

CATEGORY = 'CreateDataset_Debug'

# enter one or more directory where your source files are
# ex. ['C:/Users/david/Documents/Minecraft/Source','C:/Users/david/Documents/Minecraft/Source2']
sources = ['C:/Users/david/Documents/Minecraft/Source'] 
zoom = 17 #enter your zoom level
manual_nodata_value = None #Leave at None to use the defined NODATA value of the source file, or set it to value, if your source files don't have NODATA defined
convert_feet_to_meters = False #Set to True, if your dataset heights are in feet

cleanup = False # Set to False if you don't wish to delete VRT file and supporting files once the script completes. It will still do a cleanup, if you run the script again
thread_count = None #Set to the number of threads you want to use. Preferably don't use all threads at once. Leave at at None to use all threads

localThread = threading.local()

single_source_mode = None


# Modified version of scale_query_to_tile from gdal2tiles
#https://github.com/OSGeo/gdal/blob/master/gdal/swig/python/scripts/gdal2tiles.py
class Tile:
  def __init__(self, ds, x, y, ulx, uly, lrx, lry, dsulx, dsxres, dsuly, dsyres, querysize=0):
        #dsulx, dsxres, dsxskew, dsuly, dsyskew, dsyres = ds.GetGeoTransform()
        rx = int((ulx - dsulx) / dsxres + 0.001)
        ry = int((uly - dsuly) / dsyres + 0.001)
        rxsize = max(1, int((lrx - ulx) / dsxres + 0.5))
        rysize = max(1, int((lry - uly) / dsyres + 0.5))

        if not querysize:
            wxsize, wysize = rxsize, rysize
        else:
            wxsize, wysize = querysize, querysize

        wx = 0
        if rx < 0:
            rxshift = abs(rx)
            wx = int(wxsize * (float(rxshift) / rxsize))
            wxsize = wxsize - wx
            rxsize = rxsize - int(rxsize * (float(rxshift) / rxsize))
            rx = 0
        if rx + rxsize > ds.RasterXSize:
            wxsize = int(wxsize * (float(ds.RasterXSize - rx) / rxsize))
            rxsize = ds.RasterXSize - rx

        wy = 0
        if ry < 0:
            ryshift = abs(ry)
            wy = int(wysize * (float(ryshift) / rysize))
            wysize = wysize - wy
            rysize = rysize - int(rysize * (float(ryshift) / rysize))
            ry = 0
        if ry + rysize > ds.RasterYSize:
            wysize = int(wysize * (float(ds.RasterYSize - ry) / rysize))
            rysize = ds.RasterYSize - ry

        self.x = x
        self.y = y
        self.rx = rx
        self.ry = ry
        self.rxsize = rxsize
        self.rysize = rysize
        self.wx = wx
        self.wy = wy
        self.wxsize = wxsize
        self.wysize = wysize
        self.querysize = querysize

class Job:
    def __init__(self, zoom_level, input_file, bandsCount, datasetName):
        self.zoom_level = zoom_level
        self.input_file = input_file
        self.bandsCount = bandsCount
        self.datasetName = datasetName
        self.error_tiles = []

    def addError(self, tile_data):
        self.error_tiles.append(tile_data)
    
class TaskData:
    def __init__(self, sourceIndex, sourcesArray, timeStartedFirst):
        self.sourceIndex = sourceIndex
        self.sourcesArray = sourcesArray
        self.timeStartedFirst = timeStartedFirst

    def getDatasetName(self):
        return self.sourcesArray[self.sourceIndex].datasetName
    
    def getSourcePath(self):
        return self.sourcesArray[self.sourceIndex].sourcePath
    
    def setTilesCount(self, tiles_count):
        self.sourcesArray[self.sourceIndex].sourceTilesCount = tiles_count

    def getTilesCount(self):
        return self.sourcesArray[self.sourceIndex].sourceTilesCount
    
    def setTimeStarted(self, time_started):
        self.sourcesArray[self.sourceIndex].timeStarted = time_started

    def getTimeStarted(self):
        return self.sourcesArray[self.sourceIndex].timeStarted
    
    def setSourceBounds(self, wgs_minx, wgs_minz, wgs_maxx, wgs_maxz):
        self.sourcesArray[self.sourceIndex].sourceBounds = [wgs_minx, wgs_minz, wgs_maxx, wgs_maxz]

    def setSourceIndex(self, source_index):
        if source_index < len(self.sourcesArray):
            self.sourceIndex = source_index
            return True
        else:
            return False

    def genTaskName(self):
        return 'Debug {dataset_name} elevation dataset ({index}/{length})'.format(dataset_name=self.getDatasetName(), index=self.sourceIndex + 1, length=len(self.sourcesArray))

class SourceDataset:
    def __init__(self, source_path):
        self.sourcePath = source_path
        self.datasetName = os.path.basename(source_path)
        self.sourceTilesCount = 0
        self.timeStarted = None
        self.sourceBounds = None

class ColorRamp:
    def __init__(self, altitude, cftm):
        v = None
        if cftm:
            v = altitude * 0.3048
        else:
            v = altitude
        v += 32768
        r = math.floor(v/256)
        g = math.floor(v % 256)
        b = math.floor((v - math.floor(v)) * 256)
        self.altitude = altitude
        self.red = r
        self.green = g
        self.blue = b

class Statistic:
    def __init__(self, minV, maxV):
        self.minV = minV
        self.maxV = maxV

class FTPArchiveProgress:
    def __init__(self, totalSize, task):
        self.totalSize = totalSize
        self.task = task
        self.sizeWritten = 0
        self.lastPr = 0

    def updateProgress(self, block):
        self.sizeWritten += 1024
        pr = max(0, min(int(((self.sizeWritten * 40) / self.totalSize) + 60), 100))
        if (self.lastPr != pr):
            self.lastPr = pr
            self.task.setProgress(pr)

def genTiles(task, taskData):
    taskData.setTimeStarted(datetime.now())
    try:
        cpu_count = 1
        if thread_count is None:
            cpu_count = multiprocessing.cpu_count()
        else:
            cpu_count = thread_count

        sources_length = len(taskData.sourcesArray)
        source_folder = taskData.getSourcePath()

        files = []
        for src in glob.iglob(source_folder + '/**', recursive=True):
            if (src.endswith(".tif") or src.endswith(".tiff")
            or src.endswith(".img") or src.endswith(".IMG")):
                src = src.replace("\\","/")
                fileinfo = QFileInfo(src)
                filename = fileinfo.completeBaseName()
                files.append([src, filename])
        
        if len(files) == 0:
            taskData.setTilesCount(0)
            return taskData

        if single_source_mode:
            QgsMessageLog.logMessage(
                        'Started checking dataset out of {count} files'.format(count=len(files)),
                        CATEGORY, Qgis.Info)
        else:
            QgsMessageLog.logMessage(
                        'Started checking {count} files in {dataset_name}({index}/{length})'
                        .format(count=len(files), dataset_name=taskData.getDatasetName(), index=taskData.sourceIndex + 1, length=sources_length),
                        CATEGORY, Qgis.Info)
            

        org_vrt = os.path.join(source_folder, "OrgSource.vrt").replace("\\","/")
        if os.path.isfile(org_vrt):
            os.remove(org_vrt)
        
        org_files = []
        for file in files:
            try:
                tile_ds = gdal.Open(file[0], gdal.GA_ReadOnly)
                tile_info = gdal.Info(tile_ds, format='json')
                #Check if tiff has an positive NS resolution
                if tile_info["geoTransform"][5] > 0:
                    QgsMessageLog.logMessage('Reprojecting {tile_name} duo to positive NS resolution (vertically flipped image)'.format(tile_name=file[1]), CATEGORY, Qgis.Info)
                    reprojected_tiff = os.path.join(os.path.dirname(file[0]), "{filename}_NS_Corrected{ext}".format(filename=file[1],ext=os.path.splitext(file[0])[1]))
                    #Use gdalwarp to corrent the positive NS resolution
                    gdal.Warp(reprojected_tiff, tile_ds)
                    tile_ds = None

                    #Delete original file
                    os.remove(file[0])
                    #Rename reprojected tiff to original file name
                    os.rename(reprojected_tiff, file[0])
                else:
                    tile_ds = None

                org_files.append(file[0])
            
            except Exception as e:
                QgsMessageLog.logMessage('Skipping file: {1} | Error: {0}'.format(str(e), file[0]), CATEGORY, Qgis.Info)
                taskData.setTilesCount(0)
                return taskData
        
        org_vrt_options = None

        if manual_nodata_value is not None:
            org_vrt_options = gdal.BuildVRTOptions(resolution="highest",resampleAlg="bilinear",srcNodata=manual_nodata_value,VRTNodata=manual_nodata_value)
        else:
            nd_ds = gdal.Open(org_files[0], gdal.GA_ReadOnly)
            nd = nd_ds.GetRasterBand(1).GetNoDataValue()
            if nd is None:
                nd = 'nan'
            nd_ds = None
            
            org_vrt_options = gdal.BuildVRTOptions(resolution="highest",resampleAlg="bilinear", VRTNodata=nd)

        ds = gdal.BuildVRT(org_vrt, org_files,options=org_vrt_options)
        ds.FlushCache()

        source_no_data_value = None
        os_name = QgsApplication.osName()

        if os_name == "linux":
            if manual_nodata_value is None:
                huge_parser = etree.XMLParser(huge_tree=True)
                #Get no data value from org source vrt as string
                org_vrt_tree = etree.parse(org_vrt, parser=huge_parser)
                org_vrt_root = org_vrt_tree.getroot()
                org_vrt_band_1 = org_vrt_root.findall(".//VRTRasterBand[@band='1']")[0]
                org_vrt_band_1_no_data_entries = org_vrt_band_1.findall('.//NoDataValue')
                if org_vrt_band_1_no_data_entries is not None and len(org_vrt_band_1_no_data_entries) > 0:
                    org_vrt_band_1_no_data_entry = org_vrt_band_1_no_data_entries[0]
                    source_no_data_value = str(org_vrt_band_1_no_data_entry.text)

                if source_no_data_value == "" or source_no_data_value is None:
                    source_no_data_value = None
            else:
                source_no_data_value = str(manual_nodata_value)


        ds = None
        sleep(0.05)

        QgsMessageLog.logMessage(
                    'Created original vrt',
                    CATEGORY, Qgis.Info)

        vrt = os.path.join(source_folder, "Source.vrt").replace("\\","/")
        if os.path.isfile(vrt):
            os.remove(vrt)

        pds = gdal.Open(org_vrt)
        pds = gdal.Warp(vrt, pds, dstSRS="EPSG:3857")
        pds = None

        QgsMessageLog.logMessage('Created reprojected vrt',CATEGORY, Qgis.Info)

        terrarium_tile =  os.path.join(source_folder, "TerrariumSource.vrt").replace("\\","/")
        if os.path.isfile(terrarium_tile):
            os.remove(terrarium_tile)


        statistics = []

        task.setProgress(0)

        exxf = concurrent.futures.ThreadPoolExecutor(max_workers=cpu_count)
        fff= exxf.map(calculateStat, org_files)
        rt = 0
        cf = len(org_files)
        for res in fff:
            if res is not None:
                rt += 1
                statistics.append(res)
                task.setProgress(max(0, min(int((rt * 12) / cf), 100)))
            else:
                cf -= 1

        # Find minV and maxV from statistics

        minV = None
        maxV = None

        if len(statistics) > 1:
            for stat in statistics:
                if stat.minV is not None and stat.maxV is not None:
                    if minV is None:
                        minV = stat.minV
                    elif stat.minV < minV:
                        minV = stat.minV

                    if maxV is None:
                        maxV = stat.maxV
                    elif stat.maxV > maxV:
                        maxV = stat.maxV
        else:
            minV = statistics[0].minV
            maxV = statistics[0].maxV

        if minV is None or maxV is None:
            QgsMessageLog.logMessage('Error: Minimum and maximum height are None',CATEGORY, Qgis.Info)
            return None
        else:
            QgsMessageLog.logMessage('Minimum and maximum height are {mn} and {ma}'.format(mn=minV,ma=maxV),CATEGORY, Qgis.Info)

        statistics = None

        color_ramp_file = os.path.join(source_folder, "TerrariumSource.txt").replace("\\","/")
        if os.path.isfile(color_ramp_file):
            os.remove(color_ramp_file)
        color_ramp = []
        altitudes = []

        # Create color ramp
        for meters in range(minV, maxV):
            for fraction in range (0, 256):
                altitudes.append(meters+(fraction/256))

        exx = concurrent.futures.ThreadPoolExecutor(max_workers=cpu_count)
        ff= exx.map(createRamp, repeat(convert_feet_to_meters), altitudes)
        for res in ff:
            if res is not None:
                color_ramp.append(res)


        QgsMessageLog.logMessage(
                    'Creating color ramp file',
                    CATEGORY, Qgis.Info)
        
        color_ramp.sort(key = lambda x: x.altitude)
        f = open(color_ramp_file, "w")
        rt = 0
        cf = len(color_ramp)
        for ramp in color_ramp:
            if manual_nodata_value is not None:
                if ramp.altitude == manual_nodata_value:
                    f.write('{altitude}\t0\t0\t0\t0\n'.format(altitude=manual_nodata_value))
                    continue
            f.write('{altitude}\t{red}\t{green}\t{blue}\n'.format(altitude=ramp.altitude, red=ramp.red, green=ramp.green, blue=ramp.blue))
            rt += 1
            task.setProgress(max(0, min(int(((rt * 8) / cf) + 12), 100)))
        f.write('nv\t0\t0\t0\t0')
        f.close()
        sleep(0.05)

        QgsMessageLog.logMessage(
                    'Created color ramp file',
                    CATEGORY, Qgis.Info)

        QgsMessageLog.logMessage(
                    'Rendering vrt to terrarium format. This might take a while',
                    CATEGORY, Qgis.Info)

        dst_ds = gdal.Open(vrt)
        ds = gdal.DEMProcessing(terrarium_tile, dst_ds, 'color-relief', colorFilename=color_ramp_file, format="VRT", addAlpha=True)
        sleep(0.05)
        dst_ds = None

        QgsMessageLog.logMessage(
                    'Created vrt in terrarium format',
                    CATEGORY, Qgis.Info)
        
        #gdal.DEMProcessing with the 'color-relief' option and when the output datasource is a VRT, 
        #inserts two key-pairs at the start of  of the LUT (Look up table) element of each VRTRasterBand (including the 4th, ergo Alpha band), which It's keys are very similar to the source NODATA value
        #It does this on both Windows and Linux, with the only difference being that on Windows these two keys are more similar,
        #if not the first key being the same as the source NODATA, but on Linux these two keys are less similar to the source NODATA, compared to Windows
        #This, alongside with difference between the first and second key being greater then on Windows, 
        #and the second value pointing to the same byte value as the 3rd key-pair value (The real min height value of the dataset),
        #makes gdal/QGIS render the NODATA value as half transparent (ex. 128 byte), making the script render tiles with half-transparent areas
        #
        #To fix this bug, the script first reads the key-pairs of the LUT element of the Alpha VRTRasterBand
        #If the first key-pair key is not the same as the NODATA value, it calculates the string similarity between the first and second key-pair keys
        #If it's the similarity ratio is greater then 0.9, the script removed the 2nd key-pair
        #Finally set's the first key-pair key to the NODATA value, It's value to 0 (0 byte, ergo Transparent) 
        #and writes the changes to the VRT file
        if os_name == "linux" and source_no_data_value is not None: 
            QgsMessageLog.logMessage(
                    'Checking for no data value in alpha raster band of terrarium vrt',
                    CATEGORY, Qgis.Info)
            
            huge_parser = etree.XMLParser(huge_tree=True)
            terrarium_tile_tree = etree.parse(terrarium_tile,parser=huge_parser)
            terrarium_tile_root = terrarium_tile_tree.getroot()

            alpha_vrt_raster_band = terrarium_tile_root.findall(".//VRTRasterBand[@band='4']")[0]
            alpha_band_lut = alpha_vrt_raster_band.findall(".//LUT")[0]
            first_lut_key= alpha_band_lut.text[0:alpha_band_lut.text.index(',') - 2]
            if first_lut_key != source_no_data_value:
                
                org_lut_text = alpha_band_lut.text[alpha_band_lut.text.index(',') + 1:len(alpha_band_lut.text)]
                second_lut_key_index = org_lut_text.index(',')

                #Compare if the second LUT key is similar to the first one. If it is, remove it
                if second_lut_key_index > -1:
                    second_lut_key = org_lut_text[0:second_lut_key_index].split(':')[0]
                    first_second_match = SequenceMatcher(None, first_lut_key, second_lut_key)
                    if first_second_match.ratio() > 0.9:
                        org_lut_text = org_lut_text[second_lut_key_index + 1:len(org_lut_text)]
                
                alpha_band_lut_text = source_no_data_value + ':0,' + org_lut_text 
                alpha_band_lut.text = alpha_band_lut_text

                new_tree = etree.ElementTree(terrarium_tile_root)
                new_tree.write(terrarium_tile,pretty_print=True,xml_declaration=False,encoding="utf-8")

                QgsMessageLog.logMessage(
                    'Detected incorrect no data value ({0}) in alpha raster band of terrarium vrt. Should be: {1}. Corrected to right value'.format(first_lut_key, source_no_data_value),
                    CATEGORY, Qgis.Info)

        input_file = terrarium_tile

        QgsMessageLog.logMessage('Input file is {inp}'.format(inp=input_file), CATEGORY, Qgis.Info)
        dst_ds = gdal.Open(input_file, gdal.GA_ReadOnly)

        QgsMessageLog.logMessage('Calculating bounds', CATEGORY, Qgis.Info)

        diff = (20037508.3427892439067364 + 20037508.3427892439067364) / 2**zoom

        x_diff = diff
        y_diff = diff

        ulx, xres, xskew, uly, yskew, yres = dst_ds.GetGeoTransform()
        #lrx = ulx + (dst_ds.RasterXSize * xres)
        #lry = uly + (dst_ds.RasterYSize * yres)

        info = gdal.Info(dst_ds, format='json')

        ulx, uly = info['cornerCoordinates']['upperLeft'][0:2]
        lrx, lry = info['cornerCoordinates']['lowerRight'][0:2]

        wgs_minx, wgs_minz = info['wgs84Extent']['coordinates'][0][1][0:2]
        wgs_maxx, wgs_maxz = info['wgs84Extent']['coordinates'][0][3][0:2]

        if single_source_mode:
            QgsMessageLog.logMessage('The dataset bounds are (in WGS84 [EPSG:4326]), minX: {minX}, minZ: {minZ}, maxX: {maxX}, maxZ: {maxZ}'.format(minX=str(wgs_minx),minZ=str(wgs_minz),maxX=str(wgs_maxx),maxZ=str(wgs_maxz)), CATEGORY, Qgis.Info)
        else:
            QgsMessageLog.logMessage('The dataset bounds for the {dataset_name} dataset are (in WGS84 [EPSG:4326]), minX: {minX}, minZ: {minZ}, maxX: {maxX}, maxZ: {maxZ}'.format(dataset_name=taskData.getDatasetName(), minX=str(wgs_minx),minZ=str(wgs_minz),maxX=str(wgs_maxx),maxZ=str(wgs_maxz)), CATEGORY, Qgis.Info)

        taskData.setSourceBounds(wgs_minx, wgs_minz, wgs_maxx, wgs_maxz)
        
        base_x = 0
        base_y = 0

        start_tile_x = base_x
        start_tile_y = base_y
        min_x = -20037508.3427892439067364
        max_y = 20037508.3427892439067364

        x_tiles = 0
        y_tiles = 0

        # Find min lot
        lon = min_x
        while lon <= 20037508.3427892439067364:
            if lon >= ulx:
                break;
            start_tile_x += 1
            min_x = lon
            lon += x_diff

        # Find max lat
        lat = max_y
        while lat >= -20037508.3427892550826073:
            if lat <= uly:
                break
            start_tile_y += 1
            max_y = lat
            lat -= y_diff

        # Find how many lon tiles to make
        lon = min_x
        while lon < lrx:
            x_tiles += 1
            lon += x_diff

        # Find how many lat tiles to make
        lat = max_y
        while lat >= lry:
            y_tiles += 1
            lat -= y_diff

        if start_tile_x > 0:
            start_tile_x -= 1
        if start_tile_y > 0:
            start_tile_y -= 1

        tiled = []

        sub_min_x = min_x
        sub_max_x = min_x + x_diff
        for x in range(start_tile_x, start_tile_x + x_tiles):
            sub_min_y = max_y - y_diff
            sub_max_y = max_y
            for y in range(start_tile_y, start_tile_y + y_tiles):
                tiled.append(Tile(dst_ds, str(x), str(y), sub_min_x, sub_max_y, sub_max_x, sub_min_y, ulx, xres, uly, yres, querysize=1024))
                sub_min_y -= y_diff
                sub_max_y -= y_diff
            sub_min_x += x_diff
            sub_max_x += x_diff

        job = Job(str(zoom), input_file, getBands(dst_ds), taskData.getDatasetName())

        dst_ds = None

        # Catch error while reading dataset

        realtiles = 0

        if cpu_count == 1:
            rt = 0
            cf = len(tiled)
            for tile in tiled:
                res = tileVrt(job, tile)
                if res is not None:
                    realtiles += 1
                rt += 1
                task.setProgress(max(0, min(int(((rt * 80) / cf) + 20), 100)))

            if getattr(localThread, 'ds', None):
                del localThread.ds

        else:
            gdal_cache_max = gdal.GetCacheMax()
            gdal_cache_max_per_process = max(1024 * 1024, math.floor(gdal_cache_max / cpu_count))
            setCacheMax(gdal_cache_max_per_process)


            tpe = concurrent.futures.ThreadPoolExecutor(max_workers=cpu_count)
            tm = tpe.map(tileVrt, repeat(job), tiled)
            rt = 0
            cf = len(tiled)
            realtiles = 0
            for res in tm:
                if res is not None:
                    realtiles += 1
                rt += 1
                task.setProgress(max(0, min(int(((rt * 80) / cf) + 20), 100)))

            setCacheMax(gdal_cache_max)

        if len(job.error_tiles) > 0:
            QgsMessageLog.logMessage('Caught error tiles', CATEGORY, Qgis.Info)
            #Calculate geo extents of error tile
            #Each item is a bound in WGS84
            geo_error_tiles = []
            web_merc_proj = osr.SpatialReference()
            web_merc_proj.ImportFromEPSG(3857)
            wgs_proj = osr.SpatialReference()
            wgs_proj.ImportFromEPSG(4326)
            web_merc_to_wgs_transform = osr.CoordinateTransformation(web_merc_proj, wgs_proj)
            for error_tile in job.error_tiles:
                #Calculate top left corner coords
                t_ulx, t_uly, _ = web_merc_to_wgs_transform.TransformPoint(ulx + error_tile.rx * xres + error_tile.ry * xskew, uly + error_tile.rx * yskew + error_tile.ry * yres)
                #Calculate bottom right corner coords
                t_lrx, t_lry, _ = web_merc_to_wgs_transform.TransformPoint(ulx + (error_tile.rx + error_tile.rxsize) * xres + (error_tile.ry + error_tile.rysize) * xskew, uly + (error_tile.rx + error_tile.rxsize) * yskew + (error_tile.ry + error_tile.rysize) * yres)
                geo_error_tiles.append([t_uly, t_ulx, t_lry, t_lrx])

            error_files = {}

            for org_file in org_files:
                file_ds = gdal.Open(org_file, gdal.GA_ReadOnly)
                f_info = gdal.Info(file_ds, format='json')
                f_wgs_minx, f_wgs_minz = f_info['wgs84Extent']['coordinates'][0][1][0:2]
                f_wgs_maxx, f_wgs_maxz = f_info['wgs84Extent']['coordinates'][0][3][0:2]

                for error_tile_bound in geo_error_tiles:
                    if (((error_tile_bound[0] >= f_wgs_minx and error_tile_bound[0] <= f_wgs_maxx) and 
                         (error_tile_bound[1] >= f_wgs_minz and error_tile_bound[1] <= f_wgs_maxz)) or
                        ((error_tile_bound[2] >= f_wgs_minx and error_tile_bound[2] <= f_wgs_maxx) and 
                         (error_tile_bound[3] >= f_wgs_minz and error_tile_bound[3] <= f_wgs_maxz))):
                        if org_file in error_files:
                            file_error_tiles = error_files[org_file]
                            file_error_tiles.append(error_tile_bound)
                            error_files[org_file] = file_error_tiles
                        else:
                            file_error_tiles = []
                            file_error_tiles.append(error_tile_bound)
                            error_files[org_file] = file_error_tiles
                
                file_ds = None

            error_file_paths = error_files.keys()
            if len(error_file_paths) > 0:
                for error_file_path in error_file_paths:
                    file_error_tiles = error_files[error_file_path]
                    QgsMessageLog.logMessage('Error occured for file: {ef} with the following tiles (ulx, uly, lrx, lry):'.format(ef=error_file_path), CATEGORY, Qgis.Info)
                    for bounds in file_error_tiles:
                        QgsMessageLog.logMessage("\t{t_ulx}, {t_ulx} | {t_lrx}, {t_lrx}".format(t_ulx=bounds[0], t_uly=bounds[1], t_lrx=bounds[2], t_lry=bounds[3]), CATEGORY, Qgis.Info)
            

        # Clean up
        if cleanup:
            os.remove(org_vrt)
            os.remove(vrt)
            os.remove(color_ramp_file)
            os.remove(terrarium_tile)

            QgsMessageLog.logMessage('Cleaned up temp files', CATEGORY, Qgis.Info)


        taskData.setTilesCount(realtiles)
        return taskData
    except Exception as e:
        QgsMessageLog.logMessage('Error: ' + str(e), CATEGORY, Qgis.Info)
        traceback.print_exc()
        return None


def setCacheMax(cache_in_bytes: int):
    os.environ['GDAL_CACHEMAX'] = '%d' % int(cache_in_bytes / 1024 / 1024)
    gdal.SetCacheMax(cache_in_bytes)

def getBands(src_ds):
    bandsCount = 0
    alphaband = src_ds.GetRasterBand(1).GetMaskBand()
    if ((alphaband.GetMaskFlags() & gdal.GMF_ALPHA) or
            src_ds.RasterCount == 4 or
            src_ds.RasterCount == 2):
        bandsCount = src_ds.RasterCount - 1
    else:
        bandsCount = src_ds.RasterCount
    return bandsCount

def createRamp(cftm, altitude):
        return ColorRamp(altitude, cftm)

def calculateStat(tile):
    try:
        stat_ds = gdal.Open(tile)

        band = stat_ds.GetRasterBand(1)

        minV = None
        maxV = None

        if band.GetMinimum() is None or band.GetMaximum() is None:
            stats = band.GetStatistics(0,1)
            if band.GetMinimum() is not None and band.GetMaximum() is not None:
                minV = int(math.floor(stats[0]))
                maxV = int(math.ceil(stats[1]))
            else:
                stat_ds = None
                QgsMessageLog.logMessage(
                            'Tile: {name} is empty. Ignoring stats.'.format(name=tile),
                            CATEGORY, Qgis.Info)   
                return None
        else:
            minV = int(math.floor(band.GetMinimum()))
            maxV = int(math.ceil(band.GetMaximum()))

        stat_ds = None

        return Statistic(minV, maxV)
    except Exception as e:
        QgsMessageLog.logMessage(
                    'Error while calculating stat for tile: {name}. Error: {er}'.format(name=tile,er=str(e)),
                    CATEGORY, Qgis.Info)
        return None

# Modified version of create_base_tile from gdal2tiles
#https://github.com/OSGeo/gdal/blob/master/gdal/swig/python/scripts/gdal2tiles.py
def tileVrt(job_data, tile_data):
    try:
        ds_cache = getattr(localThread, 'ds', None)
        if ds_cache:
            ds = ds_cache
        else:
            ds = gdal.Open(job_data.input_file, gdal.GA_ReadOnly)
            localThread.ds = ds
        
        alphaband = ds.GetRasterBand(1).GetMaskBand()
        alphamask = None

        if tile_data.rxsize != 0 and tile_data.rysize != 0 and tile_data.wxsize != 0 and tile_data.wysize != 0:
            #alphamask = alphaband.ReadRaster(tile_data.rx, tile_data.ry, tile_data.rxsize, tile_data.rysize, tile_data.wxsize, tile_data.wysize)

            #Check if transparent
            if len(alphamask) == alphamask.count('\x00'.encode('ascii')):
                return None


        sleep(0.01)
    except Exception as e:
        job_data.addError(tile_data)
        traceback.print_exc()
        return None

    return tile_data


def taskComplete(task, taskData=None):
    if taskData is not None:
        time_end = datetime.now()
        eclipsed = (time_end - taskData.getTimeStarted()).total_seconds() / 60.0
        minutes = math.floor(eclipsed)
        seconds = math.floor((eclipsed - minutes) * 60)
        if single_source_mode:
            QgsMessageLog.logMessage('Done debuging dataset with {count} tiles in {minutes} minutes and {seconds} seconds'.format(count=taskData.getTilesCount(), minutes=minutes, seconds=seconds), CATEGORY, Qgis.Info)
        else:
            QgsMessageLog.logMessage('Done debuging {dataset_name} dataset ({index}/{lenght}) with {count} tiles in {minutes} minutes and {seconds} seconds'.format(dataset_name=taskData.getDatasetName(), index=taskData.sourceIndex + 1, lenght=len(taskData.sourcesArray), count=taskData.getTilesCount(), minutes=minutes, seconds=seconds), CATEGORY, Qgis.Info)

            #Move onto next source in the sources array
            if taskData.setSourceIndex(taskData.sourceIndex + 1):
                globals()['dataset_task'] = QgsTask.fromFunction(taskData.genTaskName(), genTiles, on_finished=taskComplete, taskData=taskData)
                QgsApplication.taskManager().addTask(globals()['dataset_task'])                
            else:
                time_end = datetime.now()
                eclipsed = (time_end - taskData.timeStartedFirst).total_seconds() / 60.0
                minutes = math.floor(eclipsed)
                seconds = math.floor((eclipsed - minutes) * 60)
                QgsMessageLog.logMessage('Done debuging all datasets in {minutes} minutes and {seconds} seconds'.format(minutes=minutes, seconds=seconds), CATEGORY, Qgis.Info)

sources_list = []

for source in sources:
    source_path = source.replace("\\","/")
    if source_path not in sources_list:
        sources_list.append(source_path)

single_source_mode = True
if len(sources_list) > 1:
    single_source_mode = False

sources_array = []
for source in sources_list:
    sources_array.append(SourceDataset(source))

source_one_name = sources_array[0].datasetName
task_data = TaskData(0, sources_array, datetime.now())

task_one_name = 'Debug elevation dataset'
if single_source_mode is False:
    task_one_name = task_data.genTaskName()

globals()['dataset_task'] = QgsTask.fromFunction(task_one_name, genTiles, on_finished=taskComplete, taskData=task_data)
QgsApplication.taskManager().addTask(globals()['dataset_task'])