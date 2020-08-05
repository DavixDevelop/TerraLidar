import math
import glob
import os
import multiprocessing
import subprocess
from time import sleep
from qgis.core import QgsProject
from pathlib import Path
import concurrent.futures

CATEGORY = 'GenerateDem'


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
	subprocess.check_output('\"C:\\Program Files\\CloudCompare\\CloudCompare\" -SILENT -O -GLOBAL_SHIFT AUTO  \"{file}\" -CSF -SCENES SLOPE -CLOTH_RESOLUTION 0.5 -CLASS_THRESHOLD 0.5 -RASTERIZE -GRID_STEP 1 -VERT_DIR 2 -PROJ MIN -SF_PROJ AVG -EMPTY_FILL INTERP -OUTPUT_RASTER_Z'.format(file=file_data[0]), cwd=lidar_directory, shell=True)
	sleep(1)
	for old_tif in Path(lidar_directory).rglob('{filename}_ground_points*.tif'.format(filename=file_data[1])):
		os.rename(old_tif, os.path.join(lidar_directory, "{filename}.tif".format(filename=file_data[1])))
	for other_tif in Path(lidar_directory).rglob('{filename}_*.tif'.format(filename=file_data[1])):
		os.remove(other_tif)
	sleep(1)
	return file_data[1]

  
lidar_directory  = "C:\\Users\\david\\Documents\\Minecraft\\Lidar"

raw_files = os.listdir(lidar_directory)

files = []



for raw_file in raw_files:
	if raw_file.endswith(".laz") or raw_file.endswith(".las"):
		fl = os.path.join(lidar_directory, raw_file)
		fileinfo = QFileInfo(fl)
		filename = fileinfo.completeBaseName()
		files.append([fl, filename])

QgsMessageLog.logMessage('Found {count} lidar files'.format(count=len(files)),CATEGORY, Qgis.Info)

process_task = QgsTask.fromFunction('Finished generatings dem for {0} files'.format(len(files)), processFiles, on_finished=filesProccesed, filesData=files)
QgsApplication.taskManager().addTask(process_task)

#if len(task_files) > 0:
#	process_task = QgsTask.fromFunction('Finished generatings dem for {0} files'.format(len(task_files)), processFiles, on_finished=filesProccesed, filesData=task_files)
#	QgsApplication.taskManager().addTask(process_task)
#	QgsMessageLog.logMessage('Added new task with {count} files'.format(count=len(task_files)),CATEGORY, Qgis.Info)	