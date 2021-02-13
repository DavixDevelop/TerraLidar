import math
import glob
import os
import multiprocessing
import subprocess
import gdal
from time import sleep
from qgis.core import QgsProject
from pathlib import Path
import concurrent.futures
import shutil

CATEGORY = 'ConvertDem'
source_directory  = "C:\\Users\\david\\Documents\\Minecraft\\Source" #enter directory with source files
dem_directory = "C:\\Users\\david\\Documents\\Minecraft\\DEM" #enter directory where you want to save the converted dem files


def processFiles(task, filesData):
	result=len(filesData)
	QgsMessageLog.logMessage(
				'Started processing {count} files'.format(count=len(filesData)),
				CATEGORY, Qgis.Info)
	cpu_count = multiprocessing.cpu_count()
	cpu_count = min(6, cpu_count)
	ex = concurrent.futures.ThreadPoolExecutor(max_workers=cpu_count)
	f = ex.map(processFile, filesData)
	for res in f:
		QgsMessageLog.logMessage(
				'Processed file {name}'.format(name=res),
				CATEGORY, Qgis.Info)
	return result

def filesProccesed(task, result=None):
	if result is not None:
		QgsMessageLog.logMessage('Done converting {files_count} files'.format(files_count=result),CATEGORY, Qgis.Info)


def processFile(file_data):
	tileName = file_data[1] + ".tif"
	tile = os.path.join(dem_directory, tileName)
	ds = gdal.Open(file_data[0])
	sleep(1)
	#Visit https://gdal.org/python/osgeo.gdal-module.html#TranslateOptions to see other options, like width and height for a higher resolution
	ds = gdal.Translate(tile,ds,format="GTiff",resampleAlg="cubic")
	ds = None
	sleep(1)
	return file_data[1]

files = []

#Change the asc or xyz extension, to whatever extension your raster data source uses, but first check if gdal can open it.
for raw_file in glob.iglob(source_directory + '**/**', recursive=True):
	if raw_file.endswith(".asc") or raw_file.endswith(".xyz"):
		fl = os.path.join(source_directory, raw_file)
		fileinfo = QFileInfo(fl)
		filename = fileinfo.completeBaseName()
		files.append([fl, filename])

QgsMessageLog.logMessage('Found {count} files'.format(count=len(files)),CATEGORY, Qgis.Info)

process_task = QgsTask.fromFunction('Finished converting {0} files'.format(len(files)), processFiles, on_finished=filesProccesed, filesData=files)
QgsApplication.taskManager().addTask(process_task)