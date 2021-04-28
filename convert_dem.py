import math
import glob
import os
import multiprocessing
import subprocess
from osgeo import gdal
from time import sleep
from qgis.core import QgsProject
from pathlib import Path
import concurrent.futures
import shutil
from datetime import datetime
from itertools import repeat

CATEGORY = 'ConvertDem'
#This script assumes that each row in the source file contains the colums in the next order: x, y, z
source_directory  = "C:/Users/david/Documents/Minecraft/Source" #enter directory with source files
source_epsg = None #Set the source projection, which will be also used for the output projection, ex. "EPSG:3794". Leave at None to ignore. else make sura that you set it to 'EPSG:<YOUR EPSG CODE>'
dem_directory = "C:/Users/david/Documents/Minecraft/DEM" #enter directory where you want to save the converted dem files

recursive = False #Set to True if you want the script to also scan for files in sub-folders
thread_count = None #Set to the number of threads you want to use. Preferably don't use all threads at once. Leave at at None to use all threads

gdal.UseExceptions()

class FileData:
    def __init__(self, filePath, fileName):
        self.filePath = filePath
        self.fileName = fileName

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

    ex = concurrent.futures.ThreadPoolExecutor(max_workers=cpu_count)
    f = ex.map(processFile, repeat(source_epsg) filesData)
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


def processFile(sourceEpsg, file_data):
    try:
        tileName = file_data.fileName + ".tif"
        tile = os.path.join(dem_directory, tileName)
        ds = gdal.Open(file_data.filePath)
        sleep(0.05)
        #Visit https://gdal.org/python/osgeo.gdal-module.html#TranslateOptions to see other options, like width and height for a higher resolution
        if sourceEpsg is None:
            ds = gdal.Translate(tile,ds,format="GTiff",resampleAlg="cubic")
            ds = None
        else:
            ds = gdal.Translate(tile,ds,format="GTiff",outputSRS=sourceEpsg,resampleAlg="cubic")
            ds = None

        sleep(0.05)
        return file_data
    except Exception as e:
        QgsMessageLog.logMessage('Error while converting {file}, Error: {er}'.format(file=file_data.fileName, er=str(e)),CATEGORY, Qgis.Info)

    return None

process_task = QgsTask.fromFunction('Converting to DEM'.format(len(files)), processFiles, on_finished=filesProccesed)
QgsApplication.taskManager().addTask(process_task)
