import math
import glob
import os
import sys
from osgeo import gdal
from osgeo import gdalconst
from qgis.utils import iface
from qgis.core import QgsProject
from qgis.core import QgsApplication
from pathlib import Path
import shutil
from time import sleep
import multiprocessing
from multiprocessing import Pool
import concurrent.futures
import subprocess
import numpy
from itertools import repeat
from functools import partial
from datetime import datetime
from operator import itemgetter
import threading
from ftplib import FTP_TLS
from ftplib import FTP
from lxml import etree
from difflib import SequenceMatcher

try:
    from PIL import Image
    import numpy
    import osgeo.gdal_array as gdalarray
    numpy_available = True
except ImportError:
    # 'antialias' resampling is not available
    numpy_available = False


CATEGORY = 'CreateDataset'

# enter one or more directory where your source files are
# ex. ['C:/Users/david/Documents/Minecraft/Source','C:/Users/david/Documents/Minecraft/Source2']
sources = ['C:/Users/david/Documents/Minecraft/Source'] 
# enter directory where you want to save the generated dataset/datasets. If you are going to upload the dataset via ftp, you don't need to change this
#output_directory = 'C:/Users/david/Documents/Minecraft/Tiled'
zoom = 15 # enter your zoom level
resampling_algorithm = 'near' # use near for most accurate color. Look at the resampling algorithm's comparison image on the wiki for other algorithms
manual_nodata_value = None #Leave at None to use the defined NODATA value of the source file, or set it to value, if your source files don't have NODATA defined
convert_feet_to_meters = False #Set to True, if your dataset heights are in feet

ftp_upload = False # Set to True for upload to FTP server
ftp_one_file = False #Set to True to upload one zip file (RenderedDataset.zip) to FTP server
ftp_s = False # Set to True, if you want to upload to a FTPS server
ftp_upload_url = '' # FTP url to upload to (Only IP address or domain, ex 192.168.0.26)
ftp_upload_port = 21 # FTP port, ex. 2121. Must be set
# FTP folder to upload zoom folder to, ex. 'Dataset/Tiled'. Leave at None if you want to upload zoom folder to ftp server root
ftp_upload_folder = None
ftp_user = None # Leave at None for anonymous login, else set to user name, ex. 'davix'
ftp_password = None # Leave at None for anonymous login, else set to user password, ex. 'password'

cleanup = True # Set to False if you don't wish to delete VRT file and supporting files once the script completes. It will still do a cleanup, if you run the script again
thread_count = None #Set to the number of threads you want to use. Preferably don't use all threads at once. Leave at at None to use all threads

localThread = threading.local()

single_source_mode = None

try:
    import zipfile
except ImportError:
    ftpOnefile = False


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
    def __init__(self, zoom_folder, zoom_level, input_file, bandsCount, resampling, ftpUpload, ftpOnefile, ftpS, ftpUrl, ftpPort, ftpFolder, ftpUser, ftpPassword, datasetName):
        self.zoom_folder = zoom_folder
        self.zoom_level = zoom_level
        self.input_file = input_file
        self.bandsCount = bandsCount
        self.resampling = resampling
        self.ftpUpload = ftpUpload
        self.ftpOnefile = ftpOnefile
        self.ftpS = ftpS
        self.ftpUrl = ftpUrl
        self.ftpPort = ftpPort
        self.ftpFolder = ftpFolder
        self.ftpUser = ftpUser
        self.ftpPassword = ftpPassword
        self.datasetName = datasetName
    
class TaskData:
    def __init__(self, datasetName, sourceIndex, sourcesArray, timeStartedFirst):
        self.datasetName = datasetName
        self.sourceIndex = sourceIndex
        self.sourcesArray = sourcesArray
        self.timeStartedFirst = timeStartedFirst
        self.reset()
    
    def reset(self):
        self.sourceTilesCount = 0
        self.timeStarted = None
    
    def setTilesCount(self, tiles_count):
        self.sourceTilesCount = tiles_count
    
    def setTimeStarted(self, time_started):
        self.timeStarted = time_started

    def genTaskName(self):
        return 'Create {dataset_name} elevation dataset ({index}/{length})'.format(dataset_name=self.datasetName, index=self.sourceIndex + 1, length=len(self.sourcesArray))

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
        source_folder = taskData.sourcesArray[taskData.sourceIndex]
        taskData.datasetName = os.path.basename(source_folder)

        files = []
        for src in glob.iglob(source_folder + '**/**', recursive=True):
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
                        'Started creating dataset out of {count} files'.format(count=len(files)),
                        CATEGORY, Qgis.Info)
        else:
            QgsMessageLog.logMessage(
                        'Started processing {count} files in {dataset_name}({index}/{length}) to the combined output dataset'
                        .format(count=len(files), dataset_name=taskData.datasetName, index=taskData.sourceIndex + 1, length=sources_length),
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
            org_vrt_options = gdal.BuildVRTOptions(resolution="highest",resampleAlg="bilinear")

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

        org_files = None

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
            QgsMessageLog.logMessage('The dataset bounds for the {dataset_name} dataset are (in WGS84 [EPSG:4326]), minX: {minX}, minZ: {minZ}, maxX: {maxX}, maxZ: {maxZ}'.format(dataset_name=taskData.datasetName, minX=str(wgs_minx),minZ=str(wgs_minz),maxX=str(wgs_maxx),maxZ=str(wgs_maxz)), CATEGORY, Qgis.Info)
        
        QgsMessageLog.logMessage('Use this info for following step F in Part two: Generating/using your dataset',CATEGORY, Qgis.Info)

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

        QgsMessageLog.logMessage('Start tile: {tx} ({mlon}), {ty} ({mxlat}), Tiles to generate: {xt} (Width: {xtx} Height: {xty})'.format(tx=start_tile_x, mlon=min_x, ty=start_tile_y, mxlat=max_y, xt=((x_tiles + 1) * (y_tiles + 1)), xtx=x_tiles,xty=y_tiles), CATEGORY, Qgis.Info)

        if single_source_mode:
            QgsMessageLog.logMessage('Creating output folders', CATEGORY, Qgis.Info)
        else:
            QgsMessageLog.logMessage('Creating output folders for {dataset_name} dataset'.format(dataset_name=taskData.datasetName), CATEGORY, Qgis.Info)

        mx = start_tile_x + x_tiles
        zoom_folder = ''
        temp_folder = os.path.join(source_folder, 'TEMP')
        if not ftp_upload:
            if single_source_mode:
                zoom_folder = os.path.join(output_directory, str(zoom)).replace("\\","/")
            else:
                output_directory_dataset = os.path.join(output_directory, taskData.datasetName).replace("\\","/")
                if not os.path.isdir(output_directory_dataset):
                    os.mkdir(output_directory_dataset)

                zoom_folder = os.path.join(output_directory_dataset, str(zoom)).replace("\\","/")
        else:
            if os.path.isdir(temp_folder):
                shutil.rmtree(temp_folder)
            os.mkdir(temp_folder)
            zoom_folder = os.path.join(temp_folder ,str(zoom)).replace("\\","/")
        if not os.path.isdir(zoom_folder):
            os.mkdir(zoom_folder)
        for x in range(start_tile_x, mx):
            folderx = os.path.join(zoom_folder, str(x)).replace("\\","/")
            if not os.path.isdir(folderx):
                os.mkdir(folderx)

        zip_file_name = 'RenderedDataset.zip'
        if single_source_mode is False:
            zip_file_name = 'RenderedDataset_{dataset_name}.zip'.format(dataset_name=taskData.datasetName)
        
        zip_file = os.path.join(zoom_folder, zip_file_name).replace("\\","/")
        rd_file = None
        if ftp_upload:
            if ftp_one_file:
                rd_file = zipfile.ZipFile(zip_file, 'w', zipfile.ZIP_DEFLATED)
            else:
                QgsMessageLog.logMessage('Creating output folders on target ftp server', CATEGORY, Qgis.Info)
                ftp = None
                if ftp_s:
                    ftp = FTP_TLS()
                else:
                    ftp = FTP()
                ftp.connect(ftp_upload_url, ftp_upload_port)
                if ftp_user is None or ftp_password is None:
                    ftp.login()
                else:
                    ftp.login(user=ftp_user, passwd=ftp_password)

                if ftp_upload_folder is not None:
                    ftp.cwd(ftp_upload_folder)
                
                if single_source_mode is False:
                    if not isFTPDir(ftp, taskData.datasetName):
                        ftp.mkd(taskData.datasetName)
                    ftp.cwd(taskData.datasetName)


                if not isFTPDir(ftp, str(zoom)):
                    ftp.mkd(str(zoom))

                ftp.cwd(str(zoom))

                for x in range(start_tile_x, mx):
                    ftp.mkd(str(x))

                ftp.quit()


        sleep(0.01)

        QgsMessageLog.logMessage('Created {ct} folders'.format(ct=x_tiles), CATEGORY, Qgis.Info)

        tiled = []

        # Tile dataset
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

        job = Job(zoom_folder, str(zoom), input_file, getBands(dst_ds), resampling_algorithm, ftp_upload, ftp_one_file, ftp_s ,ftp_upload_url, ftp_upload_port, ftp_upload_folder, ftp_user, ftp_password, taskData.datasetName)

        dst_ds = None

        # Tile the dataset

        realtiles = 0

        if cpu_count == 1:
            if single_source_mode:
                QgsMessageLog.logMessage('Started tilling vrt in single-thread mode', CATEGORY, Qgis.Info)
            else:
                QgsMessageLog.logMessage('Started tilling vrt for {dataset_name}({index}/{length}) dataset in single-thread mode'.format(dataset_name=taskData.datasetName, index=taskData.sourceIndex + 1, length=sources_length), CATEGORY, Qgis.Info)
            rt = 0
            cf = len(tiled)
            for tile in tiled:
                res = tileVrt(job, tile)
                if res is not None:
                    if job.ftpUpload and job.ftpOnefile:
                        addToZIP(job, res, rd_file)
                    realtiles += 1
                rt += 1
                if job.ftpUpload and job.ftpOnefile:
                    task.setProgress(max(0, min(int(((rt * 40) / cf) + 20), 100)))
                else:
                    task.setProgress(max(0, min(int(((rt * 80) / cf) + 20), 100)))

            if getattr(localThread, 'ds', None):
                del localThread.ds

        else:
            if single_source_mode:
                QgsMessageLog.logMessage('Started tilling vrt in multithread mode with {count} threads'.format(count=cpu_count), CATEGORY, Qgis.Info)
            else:
                QgsMessageLog.logMessage('Started tilling vrt for {dataset_name}({index}/{length}) dataset in multithread mode with {count} threads'
                                         .format(dataset_name=taskData.datasetName, index=taskData.sourceIndex + 1, length=sources_length,count=cpu_count), CATEGORY, Qgis.Info)

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
                    if job.ftpUpload and job.ftpOnefile:
                        addToZIP(job, res, rd_file)
                    realtiles += 1
                rt += 1
                if job.ftpUpload and job.ftpOnefile:
                    task.setProgress(max(0, min(int(((rt * 40) / cf) + 20), 100)))
                else:
                    task.setProgress(max(0, min(int(((rt * 80) / cf) + 20), 100)))

            setCacheMax(gdal_cache_max)

        if job.ftpUpload and job.ftpOnefile:
            rd_file.close()
            totalSize = os.path.getsize(zip_file)
            QgsMessageLog.logMessage('Starting uploading rendered archive ({size} GB) out of {count} tiles'.format(count=realtiles, size=str(round(totalSize * 9.3132257461548E-10, 4))), CATEGORY, Qgis.Info)

            ftp = None
            if job.ftpS:
                ftp = FTP_TLS()
            else:
                ftp = FTP()
            ftp.connect(job.ftpUrl, job.ftpPort)

            if job.ftpUser is None or job.ftpPassword is None:
                ftp.login()
            else:
                ftp.login(user=job.ftpUser, passwd=job.ftpPassword)

            if job.ftpFolder is not None:
                ftp.cwd(job.ftpFolder)

            ftapr = FTPArchiveProgress(int(totalSize), task)

            with open(zip_file, 'rb') as rdf_file:
                ftp.storbinary('STOR {dst_zip_file}'.format(dst_zip_file=zip_file_name), rdf_file, blocksize=1024, callback=ftapr.updateProgress)

            ftp.quit()
            
            if single_source_mode:
                QgsMessageLog.logMessage('Uploaded rendered dataset archive {dst_zip_file} with {count} tiles. You can now unzip it.'.format(dst_zip_file=zip_file_name, count=realtiles), CATEGORY, Qgis.Info)
            else:
                QgsMessageLog.logMessage('Uploaded rendered dataset archive {dst_zip_file}({index}/{length}) with {count} tiles. You can now unzip it.'.format(dst_zip_file=zip_file_name,index=taskData.sourceIndex + 1, length=sources_length, count=realtiles), CATEGORY, Qgis.Info)
        elif job.ftpUpload:
            if single_source_mode:
                QgsMessageLog.logMessage('Tiled and uploaded dataset with {count} tiles to ftp server'.format(count=realtiles), CATEGORY, Qgis.Info)
            else:
                QgsMessageLog.logMessage('Tiled and uploaded {dataset_name} dataset ({index}/{length})  with {count} tiles to ftp server'.format(dataset_name=taskData.datasetName, index=taskData.sourceIndex + 1, length=sources_length, count=realtiles), CATEGORY, Qgis.Info)
        else:
            if single_source_mode:
                QgsMessageLog.logMessage('Tiled dataset with {count} tiles'.format(count=realtiles), CATEGORY, Qgis.Info)
            else:
                QgsMessageLog.logMessage('Tiled {dataset_name} dataset ({index}/{length}) with {count} tiles'.format(dataset_name=taskData.datasetName, index=taskData.sourceIndex + 1, length=sources_length, count=realtiles), CATEGORY, Qgis.Info)

        # Clean up
        if cleanup:
            os.remove(org_vrt)
            os.remove(vrt)
            os.remove(color_ramp_file)
            os.remove(terrarium_tile)

            if job.ftpUpload:
                shutil.rmtree(temp_folder)

            QgsMessageLog.logMessage('Cleaned up temp files', CATEGORY, Qgis.Info)


        taskData.setTilesCount(realtiles)
        return taskData
    except Exception as e:
        QgsMessageLog.logMessage('Error: ' + str(e), CATEGORY, Qgis.Info)
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

def isFTPDir(ftp, name):
   try:
      ftp.cwd(name)
      ftp.cwd('..')
      return True
   except:
      return False

def addToZIP(job_data, tile_data, rd_file):
    folder = os.path.join(job_data.zoom_folder, tile_data.x).replace("\\","/")
    tileName = tile_data.y + ".png"
    tile_file =  os.path.join(folder, tileName).replace("\\","/")

    #Add tile to zip
    rd_file.write(tile_file, os.path.join(job_data.zoom_level, str(tile_data.x), str(tile_data.y) + ".png"))
    #Remove tile from TEMP
    os.remove(tile_file)

# Modified version of scale_query_to_tile from gdal2tiles
#https://github.com/OSGeo/gdal/blob/master/gdal/swig/python/scripts/gdal2tiles.py
def scaleTile(dsquery, dstile, resampling, tile=''):
    querysize = dsquery.RasterXSize
    tile_size = dstile.RasterXSize
    tilebands = dstile.RasterCount

    if resampling == 'average':

        # Function: gdal.RegenerateOverview()
        for i in range(1, tilebands + 1):
            # Black border around NODATA
            res = gdal.RegenerateOverview(dsquery.GetRasterBand(i), dstile.GetRasterBand(i),
                                          'average')
            if res != 0:
                QgsMessageLog.logMessage("RegenerateOverview() failed on %s, error %d" % (
                    tile, res), CATEGORY, Qgis.Info)

    elif resampling == 'antialias' and numpy_available:

        # Scaling by PIL (Python Imaging Library) - improved Lanczos
        array = numpy.zeros((querysize, querysize, tilebands), numpy.uint8)
        for i in range(tilebands):
            array[:, :, i] = gdalarray.BandReadAsArray(dsquery.GetRasterBand(i + 1),
                                                       0, 0, querysize, querysize)
        im = Image.fromarray(array, 'RGBA')     # Always four bands
        im1 = im.resize((tile_size, tile_size), Image.ANTIALIAS)
        if os.path.exists(tile):
            im0 = Image.open(tile)
            im1 = Image.composite(im1, im0, im1)
        im1.save(tile, 'PNG')

    else:

        if resampling == 'near':
            gdal_resampling = gdal.GRA_NearestNeighbour

        elif resampling == 'bilinear':
            gdal_resampling = gdal.GRA_Bilinear

        elif resampling == 'cubic':
            gdal_resampling = gdal.GRA_Cubic

        elif resampling == 'cubicspline':
            gdal_resampling = gdal.GRA_CubicSpline

        elif resampling == 'lanczos':
            gdal_resampling = gdal.GRA_Lanczos

        elif resampling == 'mode':
            gdal_resampling = gdal.GRA_Mode

        elif resampling == 'max':
            gdal_resampling = gdal.GRA_Max

        elif resampling == 'min':
            gdal_resampling = gdal.GRA_Min

        elif resampling == 'med':
            gdal_resampling = gdal.GRA_Med

        elif resampling == 'q1':
            gdal_resampling = gdal.GRA_Q1

        elif resampling == 'q3':
            gdal_resampling = gdal.GRA_Q3

        # Other algorithms are implemented by gdal.ReprojectImage().
        dsquery.SetGeoTransform((0.0, tile_size / float(querysize), 0.0, 0.0, 0.0,
                                 tile_size / float(querysize)))
        dstile.SetGeoTransform((0.0, 1.0, 0.0, 0.0, 0.0, 1.0))

        res = gdal.ReprojectImage(dsquery, dstile, None, None, gdal_resampling)
        if res != 0:
            QgsMessageLog.logMessage("ReprojectImage() failed on %s, error %d" % (tile, res), CATEGORY, Qgis.Info)


# Modified version of create_base_tile from gdal2tiles
#https://github.com/OSGeo/gdal/blob/master/gdal/swig/python/scripts/gdal2tiles.py
def tileVrt(job_data, tile_data):
    try:
        folder = os.path.join(job_data.zoom_folder, tile_data.x).replace("\\","/")
        tileName = tile_data.y + ".png"
        tile =  os.path.join(folder, tileName).replace("\\","/")

        tilebands = job_data.bandsCount + 1

        ds_cache = getattr(localThread, 'ds', None)
        if ds_cache:
            ds = ds_cache
        else:
            ds = gdal.Open(job_data.input_file, gdal.GA_ReadOnly)
            localThread.ds = ds

        mem_drv = gdal.GetDriverByName('MEM')
        out_drv = gdal.GetDriverByName('PNG')
        alphaband = ds.GetRasterBand(1).GetMaskBand()

        dstile = mem_drv.Create('', 256, 256, job_data.bandsCount + 1)
        data = alphamask = None

        if tile_data.rxsize != 0 and tile_data.rysize != 0 and tile_data.wxsize != 0 and tile_data.wysize != 0:
            alphamask = alphaband.ReadRaster(tile_data.rx, tile_data.ry, tile_data.rxsize, tile_data.rysize, tile_data.wxsize, tile_data.wysize)

            ##Check if transparent
            if len(alphamask) == alphamask.count('\x00'.encode('ascii')):
                return None

            data = ds.ReadRaster(tile_data.rx, tile_data.ry, tile_data.rxsize, tile_data.rysize, tile_data.wxsize, tile_data.wysize, band_list=list(range(1, job_data.bandsCount + 1)))

        if data:
            if  tile_data.querysize == 256:
                dstile.WriteRaster(tile_data.wx, tile_data.wy, tile_data.wxsize, tile_data.wysize, data,
                                   band_list=list(range(1, job_data.bandsCount + 1)))
                dstile.WriteRaster(tile_data.wx, tile_data.wy, tile_data.wxsize, tile_data.wysize, alphamask, band_list=[tilebands])
            else:
                dsquery = mem_drv.Create('', tile_data.querysize, tile_data.querysize, tilebands)
                dsquery.WriteRaster(tile_data.wx, tile_data.wy, tile_data.wxsize, tile_data.wysize, data,
                                    band_list=list(range(1, job_data.bandsCount + 1)))
                dsquery.WriteRaster(tile_data.wx, tile_data.wy, tile_data.wxsize, tile_data.wysize, alphamask, band_list=[tilebands])

                scaleTile(dsquery, dstile, job_data.resampling, tile=tile)
                del dsquery

        del data

        if job_data.resampling != 'antialias':
            out_drv.CreateCopy(tile, dstile, strict=0)

        del dstile

        xmlFile = os.path.join(folder, tile_data.y + '.png.aux.xml')
        if os.path.isfile(xmlFile):
            os.remove(xmlFile)


        if job_data.ftpUpload and not job_data.ftpOnefile:
            ftp = None
            if job_data.ftpS:
                ftp = FTP_TLS()
            else:
                ftp = FTP()
            ftp.connect(job_data.ftpUrl, job_data.ftpPort)

            if job_data.ftpUser is None or job_data.ftpPassword is None:
                ftp.login()
            else:
                ftp.login(user=job_data.ftpUser, passwd=job_data.ftpPassword)

            if job_data.ftpFolder is not None:
                ftp.cwd(job_data.ftpFolder)

            if single_source_mode is False:
                ftp.cwd(job_data.datasetName)
            
            ftp.cwd(str(job_data.zoom_level) + '/' + tile_data.x)
            with open(tile, 'rb') as tile_file:
                ftp.storbinary('STOR {tileName}'.format(tileName=tileName), tile_file)

            ftp.quit()
            os.remove(tile)


        sleep(0.01)
    except Exception as e:
        QgsMessageLog.logMessage('Tiled vrt error: ' + str(e), CATEGORY, Qgis.Info)
        return None

    return tile_data

def taskComplete(task, taskData=None):
    if taskData is not None:
        time_end = datetime.now()
        eclipsed = (time_end - taskData.timeStarted).total_seconds() / 60.0
        minutes = math.floor(eclipsed)
        seconds = math.floor((eclipsed - minutes) * 60)
        if single_source_mode:
            QgsMessageLog.logMessage('Done creating dataset with {count} tiles in {minutes} minutes and {seconds} seconds'.format(count=taskData.sourceTilesCount, minutes=minutes, seconds=seconds), CATEGORY, Qgis.Info)
        else:
            QgsMessageLog.logMessage('Done creating {dataset_name} dataset ({index}/{lenght}) with {count} tiles in {minutes} minutes and {seconds} seconds'.format(dataset_name=taskData.datasetName, index=taskData.sourceIndex + 1, lenght=len(taskData.sourcesArray), count=taskData.sourceTilesCount, minutes=minutes, seconds=seconds), CATEGORY, Qgis.Info)

            #Move onto next source in the sources array
            if taskData.sourceIndex + 1 < len(taskData.sourcesArray):
                taskData.sourceIndex += 1
                taskData.reset()

                globals()['dataset_task'] = QgsTask.fromFunction(taskData.genTaskName(), genTiles, on_finished=taskComplete, taskData=taskData)
                QgsApplication.taskManager().addTask(globals()['dataset_task'])
            else:
                time_end = datetime.now()
                eclipsed = (time_end - taskData.timeStartedFirst).total_seconds() / 60.0
                minutes = math.floor(eclipsed)
                seconds = math.floor((eclipsed - minutes) * 60)
                QgsMessageLog.logMessage('Done creating all datasets in {minutes} minutes and {seconds} seconds'.format(minutes=minutes, seconds=seconds), CATEGORY, Qgis.Info)

sources_list = []

for source in sources:
    if source not in sources_list:
        sources_list.append(source)

single_source_mode = True
if len(sources_list) > 1:
    single_source_mode = False


source_one_name = os.path.basename(sources_list[0])
task_data = TaskData(source_one_name, 0, sources_list, datetime.now())

task_one_name = 'Create elevation dataset'
if single_source_mode is False:
    task_one_name = task_data.genTaskName()

globals()['dataset_task'] = QgsTask.fromFunction(task_one_name, genTiles, on_finished=taskComplete, taskData=task_data)
QgsApplication.taskManager().addTask(globals()['dataset_task'])