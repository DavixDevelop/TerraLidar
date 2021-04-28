import math
import glob
import os
import multiprocessing
import subprocess
from osgeo import gdal
from osgeo import ogr
from time import sleep
from qgis.core import QgsProject
from pathlib import Path
import concurrent.futures
import shutil
from datetime import datetime
from itertools import repeat

CATEGORY = 'ConvertTINtoRaster'
source_directory  = "C:/Users/david/Documents/Minecraft/Source" #enter directory with source files
source_epsg = 'EPSG:5514' #Set the source projection, which will be also used for the output projection, ex. "EPSG:3794". Make sura that you set it to 'EPSG:<YOUR EPSG CODE>'
source_delimiter = ' ' #Set the delimiter in the xyz or asc file, ex ',' or ';'. Leave at ' ' for space delimiter
#This script assumes that each row in the source file contains the colums in the next order: x, y, z
dem_directory = "C:/Users/david/Documents/Minecraft/DEM" #enter directory where you want to save the converted dem files

#These two options must be set, as gdal.Grid only outputs a small 256x256 image by default.
#If you have trouble finding out the image size, set the size to 256, set cleanup to 'False', run the script and drag & drop
#one vrt file into QGIS. Study the distance between points and the overall extent of the image, and decide the image width and height
#ex. if the extent of the image is 1000m x 1000m, and the averge distance between points is 1m, the size of the raster would be 1000x1000 pixels
raster_width = 1000 #Set image width
raster_height = 1000 #Set image height

recursive = False #Set to True if you want the script to also scan for files in sub-folders
thread_count = None #Set to the number of threads you want to use. Preferably don't use all threads at once. Leave at at None to use all threads

#See https://gdal.org/programs/gdal_grid.html#invdist for explanation
power = 2.0 #Set power of the invdist algorithm. Leave at 2.0 for default setting
smoothing = 0.0 #Set the smoothing of the invdist algorithm. Leave at 0.0 for no smoothing

cleanup = True # Set to False if you don't wish to delete VRT and CSV files once the script completes. It will still do a cleanup, if you run the script again

gdal.UseExceptions()

class FileData:
    def __init__(self, filePath, fileName):
        self.filePath = filePath
        self.fileName = fileName

class Job:
    def __init__(self, powerVal, smoothingVal, sourceEpsg, sourceDel, tileWidth, tileHeight):
        self.powerVal = powerVal
        self.smoothingVal = smoothingVal
        self.sourceEpsg = sourceEpsg
        self.sourceDel = sourceDel
        self.tileWidth = tileWidth
        self.tileHeight = tileHeight

def processFiles(task):
    time_start = datetime.now()
    filesData = []
    if recursive:
        #Change the asc or xyz extension, to whatever extension your raster data source uses, but first check if gdal can open it.
        for raw_file in glob.iglob(source_directory + '**/**', recursive=True):
            if raw_file.endswith(".asc") or raw_file.endswith(".xyz"):
                raw_file = raw_file.replace("\\","/")
                fileinfo = QFileInfo(raw_file)
                filename = fileinfo.completeBaseName()
                filesData.append(FileData(raw_file, filename))
    else:
        raw_files = os.listdir(source_directory)
        #Change the asc or xyz extension, to whatever extension your raster data source uses, but first check if gdal can open it.
        for raw_file in raw_files:
            if raw_file.endswith(".asc") or raw_file.endswith(".xyz"):
                fl = os.path.join(source_directory, raw_file)
                fileinfo = QFileInfo(fl)
                filename = fileinfo.completeBaseName()
                filesData.append(FileData(fl, filename))

    if len(filesData) == 0:
        QgsMessageLog.logMessage(
                'Found none source files',
                CATEGORY, Qgis.Info)
        return None

    QgsMessageLog.logMessage(
                'Started processing {count} files'.format(count=len(filesData)),
                CATEGORY, Qgis.Info)
    cpu_count = 1
    if thread_count is None:
        cpu_count = multiprocessing.cpu_count()
    else:
        cpu_count = thread_count

    job = Job(power, smoothing, source_epsg, source_delimiter, raster_width, raster_height)

    ex = concurrent.futures.ThreadPoolExecutor(max_workers=cpu_count)
    f = ex.map(processFile, repeat(job), filesData)
    p = 0
    result = 0
    for res in f:
        if res is not None:
            result += 1
        p += 1
        task.setProgress(int((p * 100) / len(filesData)))
        sleep(0.05)
    return [result, time_start]

def filesProccesed(task, result=None):
    if result is not None:
        time_end = datetime.now()
        eclipsed = (time_end - result[1]).total_seconds() / 60.0
        minutes = math.floor(eclipsed)
        seconds = math.floor((eclipsed - minutes) * 60)
        QgsMessageLog.logMessage('Done converting {files_count} files in {minutes} minutes and {seconds} seconds'.format(files_count=result[0], minutes=minutes, seconds=seconds),CATEGORY, Qgis.Info)

def processFile(job_data, file_data):
    try:
        #Set output filename
        tileName = file_data.fileName + ".tif"
        tile = os.path.join(dem_directory, tileName).replace("\\","/")

        csv_data = []

        #Open source file and create a array representing csv data
        with open(file_data.filePath, 'r') as dmr_file:
            for l in dmr_file:
                if l != "":
                    xyz_line = l.strip().split(job_data.sourceDel)
                    csv_data.append("{xc},{yc},{h}\n".format(xc=xyz_line[0],yc=xyz_line[1],h=xyz_line[2]))

        #Check if last row is empty, and remove it
        if csv_data[len(csv_data) - 1] == "":
            csv_data.pop()

        #Check if last row ends with new line, trim row
        lastrow = csv_data[len(csv_data) - 1]
        if lastrow.endswith('\n'):
            lastrow = lastrow.rstrip()
            csv_data[len(csv_data) - 1] = lastrow

        csv_file = os.path.join(dem_directory, file_data.fileName + ".csv").replace("\\","/")
        if os.path.isfile(csv_file):
            os.remove(csv_file)

        #Write csv data to file
        with open(csv_file, 'w') as csf:
            csf.writelines(csv_data)


        #Create array representing lines in a vrt file
        vrtData = []
        vrtData.append("<OGRVRTDataSource>\n")
        vrtData.append('    <OGRVRTLayer name="{name}">\n'.format(name=file_data.fileName))
        vrtData.append('        <SrcDataSource>{csvfile}</SrcDataSource>\n'.format(csvfile=csv_file))
        vrtData.append('        <GeometryType>wkbPoint25D</GeometryType>\n')
        vrtData.append('        <LayerSRS>{sepsg}</LayerSRS>\n'.format(sepsg=job_data.sourceEpsg))
        vrtData.append('        <GeometryField encoding="PointFromColumns" x="field_1" y="field_2" z="field_3"/>\n')
        vrtData.append('    </OGRVRTLayer>\n')
        vrtData.append('</OGRVRTDataSource>')



        vrt_file = os.path.join(dem_directory, file_data.fileName + ".vrt").replace("\\","/")
        if os.path.isfile(vrt_file):
            os.remove(vrt_file)

        #Write vrt to file
        with open(vrt_file, 'w') as vrf:
            vrf.writelines(vrtData)
        sleep(0.01)

        vrts = gdal.OpenEx(vrt_file, 0)

        #Visit https://gdal.org/python/osgeo.gdal-module.html#GridOptions to see other options, like width and height for a higher resolution
        option = gdal.GridOptions(format='GTiff',width=job_data.tileHeight,height=job_data.tileWidth,outputSRS=job_data.sourceEpsg,algorithm='invdist:power={pow}:smoothing={smo}'.format(pow=job_data.powerVal,smo=job_data.smoothingVal),zfield='field_3')
        #Interapolate TIN to a grid
        ds = gdal.Grid(tile,vrts,options=option)
        ds = None
        del ds

        vrts = None

        #Remove csv and vrt file
        if cleanup:
            os.remove(csv_file)
            os.remove(vrt_file)

        sleep(0.05)
        return file_data
    except Exception as e:
        QgsMessageLog.logMessage('Error while converting {file}, Error: {er}'.format(file=file_data.fileName, er=str(e)),CATEGORY, Qgis.Info)

    return None

process_task = QgsTask.fromFunction('Converting TIN to raster', processFiles, on_finished=filesProccesed)
QgsApplication.taskManager().addTask(process_task)
