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

CATEGORY = 'ExportDem'

source_directory  = "C:/Users/david/Documents/Minecraft/Source" #enter directory with source LiDAR files
dem_directory = "C:/Users/david/Documents/Minecraft/DEM" #enter directory where you want to save the generated dem files
cloud_compare_path = "C:\\Program Files\\CloudCompare\\CloudCompare" #Set it to the the path of CloudCompare
extract_ground = False #Set it to True if your LiDAR data contains both ground and off-ground points (Like trees, buildings...)

#Grid step refers to the grid size of the output raster (the unit is same as the unit of pointclouds). Ex. setting it to 1 would result in a DEM with a resolution of 1 meter
grid_step = 1

recursive = False #Set to True if you want the script to also scan for files in sub-folders
thread_count = None #Set to the number of threads you want to use. Preferably don't use all threads at once. Leave at at None to use all threads

default_nodata = -32768 #Don't change the value of nodata, if you don't know it

#QCSF plugin parameters (when extract_ground is set to True)
#Set the scene of the lidar (SLOPE - Steep slope, RELIEF, FLAT)
lidar_scene = 'SLOPE'
#Cloth resolution refers to the grid size (the unit is same as the unit of pointclouds) of cloth which is used to cover the terrain.
#The bigger cloth resolution you have set, the coarser DTM  you will get. Ex 1.0 would result in a grid size of 1 meter
cloth_resolution = 0.5
#Classification threshold refers to a threshold (the unit is same as the unit of pointclouds) to classify the pointclouds into
#ground and non-ground parts based on the distances between points and the simulated terrain. 0.5 is adapted to most of scenes.
class_threshold = 0.5

class Job:
    def __init__(self, srcDir, demDir, extractGround, cloudCompare, defNoData, gridStep, scene, clothResolution, classThreshold):
        self.srcDir = srcDir
        self.demDir = demDir
        self.extractGround = extractGround
        self.cloudCompare = cloudCompare
        self.defNoData = defNoData
        self.gridStep = gridStep
        self.scene = scene
        self.clothResolution = clothResolution
        self.classThreshold = classThreshold

class FileData:
    def __init__(self, filePath, fileName):
        self.fileName = fileName
        self.filePath = filePath

def processFiles(task):
    filesData = []

    if recursive:
        #Change the laz extension, to whatever extension your data source uses, but first check if CloudCompare can open it.
        for raw_file in glob.iglob(source_directory + '**/**', recursive=True):
            if raw_file.endswith(".laz") or raw_file.endswith(".las"):
                raw_file = raw_file.replace("\\","/")
                fileinfo = QFileInfo(raw_file)
                filename = fileinfo.completeBaseName()
                filesData.append(FileData(raw_file, filename))
    else:
        raw_files = os.listdir(source_directory)
        #Change the laz extension, to whatever extension your data source uses, but first check if CloudCompare can open it.
        for raw_file in raw_files:
            if raw_file.endswith(".laz") or raw_file.endswith(".las"):
                fl = os.path.join(source_directory, raw_file).replace("\\","/")
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

    job = Job(source_directory, dem_directory, extract_ground, cloud_compare_path, default_nodata, grid_step, lidar_scene, cloth_resolution, class_threshold)

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
    return p

def filesProccesed(task, result=None):
    if result is not None:
        QgsMessageLog.logMessage('Done generating {files_count} dem files'.format(files_count=result),CATEGORY, Qgis.Info)


def processFile(job_data, file_data):
    file_name = os.path.join(job_data.demDir, "{filename}.tif".format(filename=file_data.fileName)).replace("\\","/")

    try:

        if job_data.extractGround:
            subprocess.check_output('\"{cloud}\" -SILENT -O -GLOBAL_SHIFT AUTO  \"{file}\" -CSF -SCENES {scene} -CLOTH_RESOLUTION {clothResolution} -CLASS_THRESHOLD {classThreshold} -RASTERIZE -GRID_STEP {gridStep} -VERT_DIR 2 -PROJ MIN -SF_PROJ AVG -EMPTY_FILL INTERP -OUTPUT_RASTER_Z'.format(cloud=job_data.cloudCompare, file=file_data.filePath, scene=job_data.scene, clothResolution=str(job_data.clothResolution), classThreshold=str(job_data.classThreshold), gridStep=str(job_data.gridStep)), cwd=job_data.srcDir, shell=True)
            sleep(0.05)
            for old_tif in Path(source_directory).rglob('{filename}_ground_points*.tif'.format(filename=file_data.fileName)):
                os.rename(old_tif, os.path.join(source_directory, "{filename}.tif".format(filename=file_data.fileName)))
            for other_tif in Path(source_directory).rglob('{filename}_*.tif'.format(filename=file_data.fileName)):
                os.remove(other_tif)
            os.rename(os.path.join(source_directory, "{filename}.tif".format(filename=file_data.fileName)), file_name)
            sleep(0.05)
        else:
            subprocess.check_output('\"{cloud}\" -SILENT -O -GLOBAL_SHIFT AUTO  \"{file}\" -RASTERIZE -GRID_STEP {gridStep} -VERT_DIR 2 -PROJ MIN -SF_PROJ AVG -EMPTY_FILL INTERP -OUTPUT_RASTER_Z'.format(cloud=job_data.cloudCompare,file=file_data.filePath, gridStep=str(job_data.gridStep)), cwd=job_data.srcDir, shell=True)
            sleep(0.05)
            for old_tif in Path(source_directory).rglob('{filename}_*.tif'.format(filename=file_data.fileName)):
                os.rename(old_tif, os.path.join(source_directory, "{filename}.tif".format(filename=file_data.fileName)))
            os.rename(os.path.join(source_directory, "{filename}.tif".format(filename=file_data.fileName)), file_name)
            sleep(0.05)

    except Exception as e:
        QgsMessageLog.logMessage('Error: {err}'.format(err=str(e)))
        return None

    try:
        dst_ds = gdal.Open(file_name, gdal.GA_ReadOnly)
        rb = dst_ds.GetRasterBand(1)

        if rb.GetNoDataValue() is None:
            rb.SetNoDataValue(job_data.defNoData)

        dst_ds = None
    except Exception as e:
        QgsMessageLog.logMessage('Error while setting nodata for {filename}.tif'.format(filename=file_data.fileName),CATEGORY, Qgis.Info)

    return file_data.fileName

process_task = QgsTask.fromFunction('Exporting DEM', processFiles, on_finished=filesProccesed)
QgsApplication.taskManager().addTask(process_task)
