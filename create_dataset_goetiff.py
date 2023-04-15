import math
import glob
import os
import sys
from osgeo import gdal
from osgeo import gdalconst
from qgis.utils import iface
from qgis.core import QgsProject
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

try:
    from PIL import Image
    import numpy
    import osgeo.gdal_array as gdalarray
    numpy_available = True
except ImportError:
    # 'antialias' resampling is not available
    numpy_available = False


CATEGORY = 'CreateDatasetGeotiff'

source_folder = 'C:/Users/david/Documents/Minecraft/Source' #'C:/Users/david/Documents/Minecraft/Source' # enter direcotry where your source files are
# enter directory where you want to save the generated files. If you are going to upload the dataset via ftp, you don't need to change this
output_directory = 'C:/Users/david/Documents/Minecraft/Tiled'
zoom = 15 # enter your zoom level
resampling_algorithm = 'near' # use near for most accurate color. Look at the resampling algoritm's comparison image on the wiki for other algoritms
manual_nodata_value = None #Leave at None, to use the defined NODATA value of the source file, or set it to value, if your source file doesn't have NODATA defined
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

default_nodata = -32768 #Set to the desired nodata value (-32768 by default)

localThread = threading.local()

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
    def __init__(self, zoom_folder, zoom_level, input_file, bandsCount, resampling, nodatavalue, newnodata, ftpUpload, ftpOnefile, ftpS, ftpUrl, ftpPort, ftpFolder, ftpUser, ftpPassword):
        self.zoom_folder = zoom_folder
        self.zoom_level = zoom_level
        self.input_file = input_file
        self.bandsCount = bandsCount
        self.resampling = resampling
        self.nodatavalue = nodatavalue;
        self.newnodata = newnodata;
        self.ftpUpload = ftpUpload
        self.ftpOnefile = ftpOnefile
        self.ftpS = ftpS
        self.ftpUrl = ftpUrl
        self.ftpPort = ftpPort
        self.ftpFolder = ftpFolder
        self.ftpUser = ftpUser
        self.ftpPassword = ftpPassword

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

def genTiles(task):
    time_start = datetime.now()
    try:
        cpu_count = 1
        if thread_count is None:
            cpu_count = multiprocessing.cpu_count()
        else:
            cpu_count = thread_count

        files = []
        for src in glob.iglob(source_folder + '**/**', recursive=True):
            if (src.endswith(".tif") or src.endswith(".tiff")
            or src.endswith(".img") or src.endswith(".IMG")):
                src = src.replace("\\","/")
                fileinfo = QFileInfo(src)
                filename = fileinfo.completeBaseName()
                files.append([src, filename])

        if len(files) == 0:
            return [0, time_start]

        #cpu_count = min(6, cpu_count)
        #if cpu_count % 2 == 0:
        #    cpu_count = int(cpu_count / 2)

        # converted_source = os.path.join(source_folder, "converted").replace("\\","/")

        QgsMessageLog.logMessage(
                    'Started creating dataset out of {count} files'.format(count=len(files)),
                    CATEGORY, Qgis.Info)

        org_vrt = os.path.join(source_folder, "OrgSource.vrt").replace("\\","/")
        if os.path.isfile(org_vrt):
            os.remove(org_vrt)
        
        org_files = []
        for file in files:
            tile_ds = gdal.Open(file[0], gdal.GA_ReadOnly)
            tile_info = gdal.Info(tile_ds, format='json')
            #Check if tiff has an positive NS resolution
            if tile_info["geoTransform"][5] > 0:
                QgsMessageLog.logMessage('Reprojectiong {tile_name} duo to positive NS resolution (vertically flipped image)'.format(tile_name=file[1]), CATEGORY, Qgis.Info)
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

        ds = gdal.BuildVRT(org_vrt, org_files,resolution="highest",resampleAlg="bilinear")
        nodatavalue = ds.GetRasterBand(1).GetNoDataValue();
        ds.FlushCache()
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

        QgsMessageLog.logMessage('Created reporojected vrt',CATEGORY, Qgis.Info)

        input_file = vrt

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

        QgsMessageLog.logMessage('The dataset bounds are (in WGS84 [EPSG:4326]), minX: {minX}, minZ: {minZ}, maxX: {maxX}, maxZ: {maxZ}'.format(minX=str(wgs_minx),minZ=str(wgs_minz),maxX=str(wgs_maxx),maxZ=str(wgs_maxz)), CATEGORY, Qgis.Info)
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

        QgsMessageLog.logMessage('Creating output folders', CATEGORY, Qgis.Info)

        mx = start_tile_x + x_tiles
        zoom_folder = ''
        temp_folder = os.path.join(source_folder, 'TEMP')
        if not ftp_upload:
            zoom_folder = os.path.join(output_directory, str(zoom)).replace("\\","/")
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

        zip_file = os.path.join(zoom_folder, 'RenderedDataset.zip').replace("\\","/")
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

        job = Job(zoom_folder, str(zoom), input_file, getBands(dst_ds), resampling_algorithm, nodatavalue, default_nodata, ftp_upload, ftp_one_file, ftp_s ,ftp_upload_url, ftp_upload_port, ftp_upload_folder, ftp_user, ftp_password)
        dst_ds = None

        # Tile the dataset

        realtiles = 0

        if cpu_count == 1:
            QgsMessageLog.logMessage('Started tilling vrt in singlethread mode', CATEGORY, Qgis.Info)
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
            QgsMessageLog.logMessage('Started tilling vrt in multithread mode with {count} threads'.format(count=cpu_count), CATEGORY, Qgis.Info)

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
            QgsMessageLog.logMessage('Starting uploading renderned archive ({size} GB) out of {count} tiles'.format(count=realtiles, size=str(round(totalSize * 9.3132257461548E-10, 4))), CATEGORY, Qgis.Info)

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
                ftp.storbinary('STOR RenderedDataset.zip', rdf_file, blocksize=1024, callback=ftapr.updateProgress)

            ftp.quit()

            QgsMessageLog.logMessage('Uploaded rendered dataset archive RenderedDataset.zip with {count} tiles. You can now unzip it.'.format(count=realtiles), CATEGORY, Qgis.Info)
        elif job.ftpUpload:
            QgsMessageLog.logMessage('Tiled and uploaded dataset with {count} tiles to ftp server'.format(count=realtiles), CATEGORY, Qgis.Info)
        else:
            QgsMessageLog.logMessage('Tiled dataset with {count} tiles'.format(count=realtiles), CATEGORY, Qgis.Info)

        # Clean up
        if cleanup:
            os.remove(org_vrt)
            os.remove(vrt)

            if job.ftpUpload:
                shutil.rmtree(temp_folder)

            QgsMessageLog.logMessage('Cleaned up temp files', CATEGORY, Qgis.Info)



        return [realtiles, time_start]
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


def isFTPDir(ftp, name):
   try:
      ftp.cwd(name)
      ftp.cwd('..')
      return True
   except:
      return False

def addToZIP(job_data, tile_data, rd_file):
    folder = os.path.join(job_data.zoom_folder, tile_data.x).replace("\\","/")
    tileName = tile_data.y + ".tif"
    tile_file =  os.path.join(folder, tileName).replace("\\","/")

    #Add tile to zip
    rd_file.write(tile_file, os.path.join(job_data.zoom_level, str(tile_data.x), str(tile_data.y) + ".tif"))
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
        array = numpy.zeros((querysize, querysize, tilebands), numpy.float32)
        for i in range(tilebands):
            array[:, :, i] = gdalarray.BandReadAsArray(dsquery.GetRasterBand(i + 1),
                                                       0, 0, querysize, querysize)
        im = Image.fromarray(array, 'RGBA')     # Always four bands
        im1 = im.resize((tile_size, tile_size), Image.ANTIALIAS)
        if os.path.exists(tile):
            im0 = Image.open(tile)
            im1 = Image.composite(im1, im0, im1)
        im1.save(tile, 'TIF')

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

def noDataTile(dstile, tile_data, job_data):
    #Read the data again
    data = dstile.ReadRaster(0, 0, tile_data.querysize, tile_data.querysize, tile_data.querysize, tile_data.querysize, band_list=list(range(1, job_data.bandsCount + 1)), buf_type = gdal.GDT_Float32)
    #Create a boolean mask for the subregion (where the actaul terrain data is)
    subregion_mask = numpy.zeros((tile_data.querysize, tile_data.querysize), dtype=bool)
    subregion_mask[tile_data.wy: tile_data.wy + tile_data.wysize, tile_data.wx: tile_data.wx + tile_data.wxsize] = True
    #Convert data to a numpy array
    data_array = numpy.frombuffer(data, dtype=numpy.float32).reshape((tile_data.querysize, tile_data.querysize))
    #Set the values outside the subregion to newnodata
    data_array[~subregion_mask] = job_data.newnodata
    #Convert the data array back to the raster (byte string)
    data = data_array.tostring()

    return data

# Modified version of create_base_tile from gdal2tiles
#https://github.com/OSGeo/gdal/blob/master/gdal/swig/python/scripts/gdal2tiles.py
def tileVrt(job_data, tile_data):
    try:
        folder = os.path.join(job_data.zoom_folder, tile_data.x).replace("\\","/")
        tileName = tile_data.y + ".tif"
        tile =  os.path.join(folder, tileName).replace("\\","/")

        tilebands = job_data.bandsCount + 1

        ds_cache = getattr(localThread, 'ds', None)
        if ds_cache:
            ds = ds_cache
        else:
            ds = gdal.Open(job_data.input_file, gdal.GA_ReadOnly)
            localThread.ds = ds

        #Create memory driver 
        mem_drv = gdal.GetDriverByName('MEM')
        #Create output Geotiff driver
        out_drv = gdal.GetDriverByName('GTiff')
        #Get the mask band of the datasource
        alphaband = ds.GetRasterBand(1).GetMaskBand()

        #Create empty data source for the output tile
        dstile = mem_drv.Create('', 256, 256, job_data.bandsCount, gdal.GDT_Float32);
        data = alphamask = None

        if tile_data.rxsize != 0 and tile_data.rysize != 0 and tile_data.wxsize != 0 and tile_data.wysize != 0:
            #Get the mask alpha mask raster from the mask band
            alphamask = alphaband.ReadRaster(tile_data.rx, tile_data.ry, tile_data.rxsize, tile_data.rysize, tile_data.wxsize, tile_data.wysize)

            ##Check if transparent
            if len(alphamask) == alphamask.count('\x00'.encode('ascii')):
                return None
            
            #read the data of the bands to a data raster
            data = ds.ReadRaster(tile_data.rx, tile_data.ry, tile_data.rxsize, tile_data.rysize, tile_data.wxsize, tile_data.wysize, band_list=list(range(1, job_data.bandsCount + 1)), buf_type = gdal.GDT_Float32)

            #Check if dataset has nodata defined and the buffer has transpareny
            if job_data.nodatavalue is not None and alphamask.count('\x00'.encode('ascii')) > 0:

                #Convert data to a numpy array
                data_array = numpy.frombuffer(data, dtype=numpy.float32).reshape((tile_data.wxsize, tile_data.wysize))
                #Set the data raster to newnodata where alpha is 0
                data_array[data_array == job_data.nodatavalue] = job_data.newnodata

                #Convert the data array back to the raster (byte string)
                data = data_array.tostring();


        if data:
            if  tile_data.querysize == 256:
                dstile.WriteRaster(tile_data.wx, tile_data.wy, tile_data.wxsize, tile_data.wysize, data,
                                   band_list=list(range(1, job_data.bandsCount + 1)), buf_type = gdal.GDT_Float32)
                
                #Set te region outside the subregion to new nodata
                data = noDataTile(dstile, tile_data, job_data)

                #Write the data again
                dstile.WriteRaster(0, 0, tile_data.querysize, tile_data.querysize, data,
                                   band_list=list(range(1, job_data.bandsCount + 1)), buf_type = gdal.GDT_Float32)


            else:
                dsquery = mem_drv.Create('', tile_data.querysize, tile_data.querysize, tilebands, gdal.GDT_Float32)
                dsquery.WriteRaster(tile_data.wx, tile_data.wy, tile_data.wxsize, tile_data.wysize, data,
                                    band_list=list(range(1, job_data.bandsCount + 1)), buf_type = gdal.GDT_Float32)
                
                #Set te region outside the subregion to new nodata
                data = noDataTile(dsquery, tile_data, job_data)

                #Write the data again
                dsquery.WriteRaster(0, 0, tile_data.querysize, tile_data.querysize, data,
                                   band_list=list(range(1, job_data.bandsCount + 1)), buf_type = gdal.GDT_Float32)

                scaleTile(dsquery, dstile, job_data.resampling, tile=tile)
                del dsquery

        del data

        #Set nodata value of band
        for x in range(1, job_data.bandsCount + 1):
            dstile.GetRasterBand(x).SetNoDataValue(job_data.newnodata)

        if job_data.resampling != 'antialias':
            out_drv.CreateCopy(tile, dstile, strict=0)

        del dstile

        xmlFile = os.path.join(folder, tile_data.y + '.tif.aux.xml')
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

def tilesGenerated(task, res=None):
    if res is not None:
        time_end = datetime.now()
        eclipsed = (time_end - res[1]).total_seconds() / 60.0
        minutes = math.floor(eclipsed)
        seconds = math.floor((eclipsed - minutes) * 60)
        QgsMessageLog.logMessage('Done creating dataset with {count} tiles in {minutes} minutes and {seconds} seconds'.format(count=res[0], minutes=minutes, seconds=seconds), CATEGORY, Qgis.Info)

task = QgsTask.fromFunction('Create elevation dataset', genTiles, on_finished=tilesGenerated)
QgsApplication.taskManager().addTask(task)
