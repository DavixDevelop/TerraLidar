import math
import glob
import os
import multiprocessing
import subprocess
from osgeo import gdal
from osgeo import osr
from osgeo.gdalconst import GA_Update
from time import sleep
from qgis.core import QgsProject
from pathlib import Path
import concurrent.futures
import shutil
from itertools import repeat

CATEGORY = 'SetCRS'
source_directory  = "C:/Users/david/Documents/Minecraft/Source"  #enter directory with your tiff files
thread_count = None #Set to the number of threads you want to use. Preferably don't use all threads at once. Leave at at None to use all threads
epsg = 3857 #Set the desired epsg code

recursive = False #Set to True if you want the script to also scan for files in sub-folders

def processFiles(task):
    filesData = []

    if recursive:
        for raw_file in glob.iglob(source_directory + '**/**', recursive=True):
            if (raw_file.endswith(".tif") or raw_file.endswith(".tiff")
            or raw_file.endswith(".img") or raw_file.endswith(".IMG")):
                raw_file = raw_file.replace("\\","/")
                fileinfo = QFileInfo(raw_file)
                filename = fileinfo.completeBaseName()
                filesData.append([raw_file, filename])
    else:
        raw_files = os.listdir(source_directory)
        for raw_file in raw_files:
            if (raw_file.endswith(".tif") or raw_file.endswith(".tiff")
            or raw_file.endswith(".img") or raw_file.endswith(".IMG")):
                fl = os.path.join(source_directory, raw_file)
                fileinfo = QFileInfo(fl)
                filename = fileinfo.completeBaseName()
                filesData.append([fl, filename])

    if len(filesData) == 0:
        QgsMessageLog.logMessage(
                'Found none source files',
                CATEGORY, Qgis.Info)
        return None

    result=len(filesData)
    QgsMessageLog.logMessage(
                'Started processing {count} files'.format(count=len(filesData)),
                CATEGORY, Qgis.Info)
    cpu_count = 1
    if thread_count is None:
        cpu_count = multiprocessing.cpu_count()
    else:
        cpu_count = thread_count

    srs = osr.SpatialReference()
    srs.ImportFromEPSG(epsg)

    ex = concurrent.futures.ThreadPoolExecutor(max_workers=cpu_count)
    f = ex.map(processFile, repeat(srs), filesData)
    p = 0
    for res in f:
        QgsMessageLog.logMessage(
                'Processed file {name}'.format(name=res),
                CATEGORY, Qgis.Info)
        p += 1
        task.setProgress(int((p * 100) / len(filesData)))
        sleep(0.05)
    return result

def filesProccesed(task, result=None):
    if result is not None:
        QgsMessageLog.logMessage('Done setting CRS for {files_count} files'.format(files_count=result),CATEGORY, Qgis.Info)


def processFile(srs_data, file_data):
    ds = gdal.Open(file_data[0], GA_Update)
    sleep(0.01)
    ds.SetProjection(srs_data.ExportToWkt())
    del ds
    sleep(0.01)
    return file_data[1]

process_task = QgsTask.fromFunction('Setting projection', processFiles, on_finished=filesProccesed)
QgsApplication.taskManager().addTask(process_task)
