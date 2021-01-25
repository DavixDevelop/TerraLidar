import math
import glob
import os
import multiprocessing
import subprocess
from time import sleep
from qgis.core import QgsProject
from pathlib import Path
import concurrent.futures
import shutil

CATEGORY = 'GenerateDem'

source_directory  = "C:\\Users\\david\\Documents\\Minecraft\\Source" #enter directory with source files
dem_directory = "C:\\Users\\david\\Documents\\Minecraft\\DEM" #enter directory where you want to save the generated dem files

min_range = 1.0 #replace with your classification minium value
max_range = 2.0 #replace with your classification maximum value
scalar_index = 5 #replace with your classification index


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
		QgsMessageLog.logMessage('Done generating {files_count} dem files'.format(files_count=result),CATEGORY, Qgis.Info)


def processFile(file_data):
	subprocess.check_output('\"C:\\Program Files\\CloudCompare\\CloudCompare\" -SILENT -O -GLOBAL_SHIFT AUTO  \"{file}\" -AUTO_SAVE OFF -SET_ACTIVE_SF {index} -FILTER_SF {min} {max} -RASTERIZE -GRID_STEP 1 -VERT_DIR 2 -PROJ MIN -SF_PROJ AVG -EMPTY_FILL INTERP -OUTPUT_RASTER_Z'.format(file=file_data[0], index=scalar_index,min=min_range,max=max_range), cwd=source_directory, shell=True)
	sleep(1)
	for old_tif in Path(source_directory).rglob('{filename}_*.tif'.format(filename=file_data[1])):
		os.rename(old_tif, os.path.join(source_directory, "{filename}.tif".format(filename=file_data[1])))
	os.rename(os.path.join(source_directory, "{filename}.tif".format(filename=file_data[1])), os.path.join(dem_directory, "{filename}.tif".format(filename=file_data[1])))
	sleep(1)
	return file_data[1]

raw_files = os.listdir(source_directory)

files = []


#Change the laz extension, to whatever extension your data source uses, but first check if CloudCompare can open it.
for raw_file in raw_files:
	if raw_file.endswith(".laz") or raw_file.endswith(".las"):
		fl = os.path.join(source_directory, raw_file)
		fileinfo = QFileInfo(fl)
		filename = fileinfo.completeBaseName()
		files.append([fl, filename])

QgsMessageLog.logMessage('Found {count} lidar files'.format(count=len(files)),CATEGORY, Qgis.Info)

process_task = QgsTask.fromFunction('Finished generatings dem for {0} files'.format(len(files)), processFiles, on_finished=filesProccesed, filesData=files)
QgsApplication.taskManager().addTask(process_task)