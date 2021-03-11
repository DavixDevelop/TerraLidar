import math
import glob
import os
import multiprocessing
import subprocess
from osgeo import gdal
from osgeo.gdalconst import GA_Update
from time import sleep
from qgis.core import QgsProject
from pathlib import Path
import concurrent.futures
import shutil
from itertools import repeat

CATEGORY = 'SetNoData'
source_directory  = "C:/Users/david/Documents/Minecraft/Source"  #enter directory with your tiff files 
thread_count = None #Set to the number of threads you want to use. Preferably don't use all threads at once. Leave at at None to use all threads
nodata = 0 #Set the value of nodata

def processFiles(task, filesData):
    result=len(filesData)
    QgsMessageLog.logMessage(
                'Started processing {count} files'.format(count=len(filesData)),
                CATEGORY, Qgis.Info)
    cpu_count = 1
    if thread_count is None:
        cpu_count = multiprocessing.cpu_count()
    else:
        cpu_count = thread_count
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=cpu_count)
    f = ex.map(processFile, repeat(nodata), filesData)
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
        QgsMessageLog.logMessage('Done setting nodata value for {files_count} files'.format(files_count=result),CATEGORY, Qgis.Info)


def processFile(no_data, file_data):
    ds = gdal.Open(file_data[0], GA_Update)
    sleep(0.01)
    for i in range(1, ds.RasterCount + 1):
        rb = ds.GetRasterBand(i)
        rb.SetNoDataValue(no_data)
        rb = None
    ds = None
    sleep(0.01)
    return file_data[1]

files = []

#Change the asc or xyz extension, to whatever extension your raster data source uses, but first check if gdal can open it.
for raw_file in glob.iglob(source_directory + '**/**', recursive=True):
    if raw_file.endswith(".tif") or raw_file.endswith(".tiff"):
        fl = os.path.join(source_directory, raw_file)
        fileinfo = QFileInfo(fl)
        filename = fileinfo.completeBaseName()
        files.append([fl, filename])

QgsMessageLog.logMessage('Found {count} files'.format(count=len(files)),CATEGORY, Qgis.Info)

process_task = QgsTask.fromFunction('Setting nodata value', processFiles, on_finished=filesProccesed, filesData=files)
QgsApplication.taskManager().addTask(process_task)