import requests
import re
import os
import csv
import multiprocessing
import subprocess
import concurrent.futures
from time import sleep
from itertools import repeat
import tarfile
import shutil
import io

CATEGORY = 'ArticDEMDownloader'

download_dir = "C:\\Users\\david\\Documents\\Minecraft\\CustomTerrain\\Svalbard\\Source" #enter directory where you wish to store the lidar data
csv_file = "C:\\Users\\david\\Documents\\Minecraft\\CustomTerrain\\Svalbard\\features.csv"

class Tile:
    def __init__(self, name, url):
        self.name = name
        self.url = url
        

def downloadFiles(task, csvFile):
    try:
        QgsMessageLog.logMessage('Started ArticDEM downloader', CATEGORY, Qgis.Info)

        cpu_count = multiprocessing.cpu_count()

        tiles = []

        with open(csvFile, newline='') as file_csv:
            reader = csv.DictReader(file_csv, delimiter=";")
            for row in reader:
                if row['spec_type'] == 'DEM':
                    tiles.append(Tile(row['name'], row['fileurl']))

        QgsMessageLog.logMessage('Completed reading csv file', CATEGORY, Qgis.Info)

        tmpTiles = tiles
        tiles = []

        for tile in tmpTiles:
            tifFile = os.path.join(download_dir, tile.name + '.tif')
            if not os.path.isfile(tifFile)
                tiles.append(tile)

        if len(tiles) == 0:
            QgsMessageLog.logMessage('All tiles are already present in the download folder', CATEGORY, Qgis.Info)
            return len(tmpTiles)

        QgsMessageLog.logMessage('Downloading tiles from ArticDEM. This make take a while.', CATEGORY, Qgis.Info)

        downloads = []

        rt = 0
        cf = len(tiles)
        download_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        dm = download_executor.map(downloadFile, repeat(download_dir), tiles)
        for res in dm:
            rt += 1
            if res is not None:
                downloads.append(res)
            task.setProgress(max(0, min(int((rt * 50) / cf), 100)))

        QgsMessageLog.logMessage('Started extracting downloaded tiles. This make take a while.', CATEGORY, Qgis.Info)

        rt = 0
        cf = len(downloads)
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=cpu_count)
        m = executor.map(extractFile, repeat(download_dir), downloads)
        for res in m:
            if res is not None:
                rt += 1
                task.setProgress(max(0, min(int(((rt * 50) / cf) + 50), 100)))
            else:
                cf -= 1
        
        return rt
    except Exception as e:
        return None

def downloadFile(downloadDir, tile):
    try:
        QgsMessageLog.logMessage('Downloading tile ' + tile.name, CATEGORY, Qgis.Info)
        archive = os.path.join(downloadDir, tile.name + '.tar.gz')
        if os.path.isfile(archive):
            QgsMessageLog.logMessage('Tile ' + tile.name + ' already downloaded', CATEGORY, Qgis.Info)
            return tile

        req = requests.get(tile.url,allow_redirects=True)
        
        with open(archive, 'wb') as fi:
            for chunk in req.iter_content(1024):
                if chunk:
                    fi.write(chunk)
            fi.close()

        QgsMessageLog.logMessage('Tile ' + tile.name + ' downloaded', CATEGORY, Qgis.Info)
        return tile
    except Exception as e:
        QgsMessageLog.logMessage('Error' + str(e), CATEGORY, Qgis.Info)
        return None

def extractFile(downloadDir, tile):
    try:
        archive = os.path.join(downloadDir, tile.name + '.tar.gz')
        target_file = tile.name + '_reg_dem.tif'
        reg_dem = os.path.join(downloadDir, target_file)
        dem = os.path.join(downloadDir, tile.name + '.tif')
        tar_file = tarfile.open(archive, mode='r|gz')
        extractAll = True
        for tarinfo in tar_file:
            if tarinfo.name == target_file:
                extractAll = False
                tar_file.extract(tarinfo, downloadDir)
                os.rename(reg_dem, dem)
                break
        if extractAll:
            source_folder = os.path.join(downloadDir, tile.name)
            os.mkdir(source_folder)
            tar_file.extractall(source_folder)

        tar_file.close()

        #os.remove(archive)
        sleep(0.01)
        return tile
    except Exception as e:
        QgsMessageLog.logMessage('Error' + str(e), CATEGORY, Qgis.Info)
        return None



def filesDownloaded(task, result=None):
    if result is not None:
        QgsMessageLog.logMessage('Finished downloading {count} source tiles'.format(count=result), CATEGORY, Qgis.Info)

task = QgsTask.fromFunction('Downloading tiles', downloadFiles, on_finished=filesDownloaded, csvFile=csv_file)
QgsApplication.taskManager().addTask(task)