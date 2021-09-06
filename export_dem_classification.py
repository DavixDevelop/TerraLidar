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
from itertools import repeat
from osgeo import gdal
from osgeo import gdalconst
from osgeo import osr

CATEGORY = 'GenerateDem'

source_directory  = "C:\\Users\\david\\Documents\\Minecraft\\Source" #enter directory with source files
dem_directory = "C:\\Users\\david\\Documents\\Minecraft\\DEM" #enter directory where you want to save the generated dem files

min_range = 1.0 #replace with your classification minium value
max_range = 2.0 #replace with your classification maximum value
scalar_index = 5 #replace with your classification index

dem_epsg = None #Set the desired epsg code, ex 4326, else keep at None

thread_count = None #Set to the number of threads you want to use. Preferably don't use all threads at once. Leave at at None to use all threads

class Job:
	def __init__(self, minRange, maxRange, scalarIndex, proj):
		self.minRange = minRange
		self.maxRange = maxRange
		self.scalarIndex = scalarIndex
		self.proj = proj

def processFiles(task, filesData):
	result=len(filesData)
	QgsMessageLog.logMessage(
				'Started processing {count} files'.format(count=len(filesData)),
				CATEGORY, Qgis.Info)
	cpu_count = 1
	if thread_count is None:
		cpu_count = multiprocessing.cpu_count()
		cpu_count = min(3, cpu_count)
	else:
		cpu_count = thread_count

	proj = None
	if dem_epsg is not None:
		proj = osr.SpatialReference()
		proj.ImportFromEPSG(dem_epsg)

	job = Job(min_range, max_range, scalar_index, proj)
	ex = concurrent.futures.ThreadPoolExecutor(max_workers=cpu_count)
	f = ex.map(processFile, repeat(job), filesData)
	p = 0
	for res in f:
		if res is not None:
			QgsMessageLog.logMessage(
					'Processed file {name}'.format(name=res),
					CATEGORY, Qgis.Info)
			p += 1
			task.setProgress(int((p * 100) / len(filesData)))
			sleep(0.05)
	return result

def filesProccesed(task, result=None):
	if result is not None:
		QgsMessageLog.logMessage('Done generating {files_count} dem files'.format(files_count=result),CATEGORY, Qgis.Info)


def processFile(job_data, file_data):
	try:
		target_file = os.path.join(dem_directory, "{filename}.tif".format(filename=file_data[1])).replace("\\","/")
		subprocess.check_output('\"C:\\Program Files\\CloudCompare\\CloudCompare\" -SILENT -O -GLOBAL_SHIFT AUTO  \"{file}\" -AUTO_SAVE OFF -SET_ACTIVE_SF {index} -FILTER_SF {min} {max} -RASTERIZE -GRID_STEP 1 -VERT_DIR 2 -PROJ MIN -SF_PROJ AVG -EMPTY_FILL INTERP -OUTPUT_RASTER_Z'.format(file=file_data[0], index=job_data.scalarIndex,min=job_data.minRange,max=job_data.maxRange), cwd=source_directory, shell=True)
		sleep(0.05)
		for old_tif in Path(source_directory).rglob('{filename}_*.tif'.format(filename=file_data[1])):
			os.rename(old_tif, os.path.join(source_directory, "{filename}.tif".format(filename=file_data[1])).replace("\\","/"))
		os.rename(os.path.join(source_directory, "{filename}.tif".format(filename=file_data[1])).replace("\\","/"), target_file)
		sleep(0.05)

		if job_data.proj is not None:
			ds = gdal.Open(target_file, GA_Update)
			sleep(0.01)
			ds.SetProjection(job_data.proj.ExportToWkt())
			del ds
			sleep(0.01)

		return file_data[1]
	except Exception as e:
		QgsMessageLog.logMessage(
					'Error while processing {name} files. Error: {er}'.format(name=file_data[1],er=str(e)))
		return None

raw_files = os.listdir(source_directory)

files = []


#Change the laz extension, to whatever extension your data source uses, but first check if CloudCompare can open it.
for raw_file in raw_files:
	if raw_file.endswith(".laz") or raw_file.endswith(".las"):
		fl = os.path.join(source_directory, raw_file).replace("\\","/")
		fileinfo = QFileInfo(fl)
		filename = fileinfo.completeBaseName()
		files.append([fl, filename])

QgsMessageLog.logMessage('Found {count} lidar files'.format(count=len(files)),CATEGORY, Qgis.Info)

process_task = QgsTask.fromFunction('Finished generatings dem for {0} files'.format(len(files)), processFiles, on_finished=filesProccesed, filesData=files)
QgsApplication.taskManager().addTask(process_task)
