import math
import glob
import os
import sys
from osgeo import gdal
from osgeo import gdalconst
from qgis.utils import iface
from qgis.core import QgsProject
from qgis.core import QgsApplication
import shutil
from time import sleep
import multiprocessing
from datetime import datetime
import threading
from ftplib import FTP_TLS
from ftplib import FTP
from lxml import etree
import json
import io

try:
    from PIL import Image
    import numpy
    import osgeo.gdal_array as gdalarray
    numpy_available = True
except ImportError:
    # 'antialias' resampling is not available
    numpy_available = False


CATEGORY = 'CreateHeightsConfig'

# enter one or more directory where your source files are
# ex. ['C:/Users/david/Documents/Minecraft/Source','C:/Users/david/Documents/Minecraft/Source2']
sources = ['C:/Users/david/Documents/Minecraft/Source']
# enter directory where you want to save the generated heights config. 
#If you wish to upload the heights config via ftp, change it to the path on your server (ex. Dataset/Tiled)
#Set it to None if you want to upload the heights config to root folder of your FTP/SFTP user
output = 'C:/Users/david/Documents/Minecraft/Tiled'
zoom = 15 #enter your zoom level
manual_nodata_value = None #Leave at None to use the defined NODATA value of the source file, or set it to value, if your source files don't have NODATA defined

ftp_upload = False # Set to True for upload to FTP server
ftp_s = False # Set to True, if you want to upload to a FTPS server
ftp_upload_url = '' # FTP url to upload to (Only IP address or domain, ex 192.168.0.26)
ftp_upload_port = 21 # FTP port, ex. 2121. Must be set
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
        return 'Calculate bounds for {dataset_name} dataset ({index}/{length})'.format(dataset_name=self.getDatasetName(), index=self.sourceIndex + 1, length=len(self.sourcesArray))

class SourceDataset:
    def __init__(self, source_path):
        self.sourcePath = source_path
        self.datasetName = os.path.basename(source_path)
        self.sourceTilesCount = 0
        self.timeStarted = None
        self.sourceBounds = None

def genBounds(task, taskData):
    taskData.setTimeStarted(datetime.now())
    try:
        sources_length = len(taskData.sourcesArray)
        source_folder = taskData.getSourcePath()

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
                        'Started creating heights config out of {count} files'.format(count=len(files)),
                        CATEGORY, Qgis.Info)
        else:
            QgsMessageLog.logMessage(
                        'Started processing {count} files in {dataset_name}({index}/{length}) to the combined heights config'
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
            org_vrt_options = gdal.BuildVRTOptions(resolution="highest",resampleAlg="bilinear")

        ds = gdal.BuildVRT(org_vrt, org_files,options=org_vrt_options)
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

        QgsMessageLog.logMessage('Created reprojected vrt',CATEGORY, Qgis.Info)

        QgsMessageLog.logMessage('Input file is {inp}'.format(inp=vrt), CATEGORY, Qgis.Info)
        dst_ds = gdal.Open(vrt, gdal.GA_ReadOnly)

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
        
        QgsMessageLog.logMessage('Optional: Take note of these bounds if you want to manually create the entries in heights.json \n as described in step F. of Part two: Generating/using your dataset',CATEGORY, Qgis.Info)

        taskData.setSourceBounds(wgs_minx, wgs_minz, wgs_maxx, wgs_maxz)
        
        # Clean up
        if cleanup:
            os.remove(org_vrt)
            os.remove(vrt)

            if ftp_upload:
                shutil.rmtree(temp_folder)

            QgsMessageLog.logMessage('Cleaned up temp files', CATEGORY, Qgis.Info)
        taskData.setTilesCount(0)
        return taskData
    except Exception as e:
        QgsMessageLog.logMessage('Error: ' + str(e), CATEGORY, Qgis.Info)
        return None

def getHeightsEntry(url_path, zoom_level, minx, minz, maxx, maxz):
    height_entry = {
        "dataset" : {
            "urls" : [ url_path],
            "projection" : {
                "web_mercator" : {
                    "zoom" : zoom_level
                }
            },
            "resolution" : 256,
            "blend" : "CUBIC",
            "parse" : {
                "parse_png_terrarium" : {}
            }
        },
        "bounds" : {
            "minX" : minx,
            "maxX" : maxx,
            "minZ" : minz,
            "maxZ" : maxz
        },
        "zooms" : {
            "min" : 0,
            "max" : 3
        },
        "priority" : 100
    }

    return height_entry
    

def genHeightsConfig(taskData):
    sources_array = taskData.sourcesArray
    heights_list = []

    for source in sources_array:
        wgs_minx, wgs_minz, wgs_maxx, wgs_maxz = source.sourceBounds
        url_path = "file://"
        if output is not None:
            url_path += f"{output}/"
        if single_source_mode is False:
            url_path += f"{source.datasetName}/"
        url_path += str(zoom) + "/${x}/${z}.png"

        heights_list.append(getHeightsEntry(url_path, zoom, wgs_minx, wgs_minz, wgs_maxx, wgs_maxz))

    raw_json = json.dumps(heights_list, indent=4)

    if ftp_upload:
        #Upload heights config to the server via ftp
        
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

        if output is not None:
            ftp.cwd(output)

        json_byte = io.BytesIO()
        json_byte.write(raw_json.encode())
        json_byte.seek(0)

        ftp.storbinary('STOR heightsTemplate.json', json_byte)

        if output is not None:
            QgsMessageLog.logMessage(f"Uploaded heightsTemplate.json to the {output} folder on your server", 
                CATEGORY, 
                Qgis.Info)
        else:
            QgsMessageLog.logMessage("Uploaded heightsTemplate.json to the root folder of your server", 
                CATEGORY, 
                Qgis.Info)

    elif output is not None:
        heights_template_path = os.path.join(output, "heightsTemplate.json")

        with open(heights_template_path, "w") as heightsTemplate:
            heightsTemplate.write(raw_json)

        QgsMessageLog.logMessage(f"Created heightsTemplate.json in the {output} folder", 
                CATEGORY, 
                Qgis.Info)
    
    QgsMessageLog.logMessage("Head to step F. of Part two: Generating/using your dataset to set it up", CATEGORY, Qgis.Info)


def taskComplete(task, taskData=None):
    if taskData is not None:
        time_end = datetime.now()
        eclipsed = (time_end - taskData.getTimeStarted()).total_seconds() / 60.0
        minutes = math.floor(eclipsed)
        seconds = math.floor((eclipsed - minutes) * 60)
        if single_source_mode:
            QgsMessageLog.logMessage('Done creating heights config in {minutes} minutes and {seconds} seconds'.format(minutes=minutes, seconds=seconds), CATEGORY, Qgis.Info)
        else:
            QgsMessageLog.logMessage('Done calculating bounds for {dataset_name} dataset ({index}/{lenght}) in {minutes} minutes and {seconds} seconds'.format(dataset_name=taskData.getDatasetName(), index=taskData.sourceIndex + 1, lenght=len(taskData.sourcesArray), minutes=minutes, seconds=seconds), CATEGORY, Qgis.Info)

            #Move onto next source in the sources array
            if taskData.setSourceIndex(taskData.sourceIndex + 1):
                globals()['dataset_task'] = QgsTask.fromFunction(taskData.genTaskName(), genBounds, on_finished=taskComplete, taskData=taskData)
                QgsApplication.taskManager().addTask(globals()['dataset_task'])                
            else:
                time_end = datetime.now()
                eclipsed = (time_end - taskData.timeStartedFirst).total_seconds() / 60.0
                minutes = math.floor(eclipsed)
                seconds = math.floor((eclipsed - minutes) * 60)
                QgsMessageLog.logMessage('Done creating a combined heights config in {minutes} minutes and {seconds} seconds. Head to the {output_folder} folder to view it'.format(minutes=minutes, seconds=seconds, output_folder=output), CATEGORY, Qgis.Info)
                genHeightsConfig(taskData)

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

task_one_name = 'Create heights config'
if single_source_mode is False:
    task_one_name = task_data.genTaskName()

output = output.replace("\\","/")

globals()['dataset_task'] = QgsTask.fromFunction(task_one_name, genBounds, on_finished=taskComplete, taskData=task_data)
QgsApplication.taskManager().addTask(globals()['dataset_task'])