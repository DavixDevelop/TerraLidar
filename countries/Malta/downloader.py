import requests
import re
import os
import multiprocessing
import subprocess
import concurrent.futures
from time import sleep
import shutil

CATEGORY = 'MaltaLidarDownloader'

download_dir = "C:\\Users\\david\\Documents\\Minecraft\\CustomTerrain\\Valletta\\Source" #enter directory where you wish to store the lidar data
grid_tiles = ["456_3972","456_3973","455_3972","455_3973"] #enter one or more tile names

def downloadFiles(task, tiles):
    
    for tile in tiles:
        #Check if folder with tile name already exists and delete it
        if os.path.isdir(os.path.join(download_dir, tile)):
           shutil.rmtree(os.path.join(download_dir, tile))
        os.mkdir(os.path.join(download_dir, tile))

        #Get list of subfragments
        fr = requests.get("http://www.um.edu.mt/projects/cloudisle/DATA1/webpublish/pointclouds/" + tile + "/data/r/")
        dl = re.findall(r'href="(r[0-9].laz)',fr.text)
        dl = dl + re.findall(r'href="(r[0-9][0-9].laz)',fr.text)
        dl = dl + re.findall(r'href="(r[0-9][0-9][0-9].laz)',fr.text)
        dl = dl + re.findall(r'href="(r[0-9][0-9][0-9][0-9].laz)',fr.text)
        data = []
        for d in dl:
            data.append([d, "http://www.um.edu.mt/projects/cloudisle/DATA1/webpublish/pointclouds/" + tile + "/data/r/" + d, tile])
        QgsMessageLog.logMessage(
            'Started downloading {count} files for tile {tile}'.format(count=len(data),tile=tile),
            CATEGORY, Qgis.Info)
        cpu_count = multiprocessing.cpu_count()
        ex = concurrent.futures.ThreadPoolExecutor(max_workers=cpu_count)
        f = ex.map(downloadFile, data)
        c = 0
        g = 0
        d_data = [[0, tile,[]]]
        #Download subfragments
        for res in f:
            d_data[g][2].append(res) 
            if c == 100:
                c = 0
                g = g + 1
                d_data.append([g, tile, []])
            c = c + 1

        QgsMessageLog.logMessage('Finished downloading {count} files for tile {tile}'.format(count=len(data),tile=tile),CATEGORY,Qgis.Info)

        f_command = '\"C:\\Program Files\\CloudCompare\\CloudCompare\" -SILENT '


        #Join 100 fragemnts into one file
        exx = concurrent.futures.ThreadPoolExecutor(max_workers=cpu_count)
        ff = exx.map(mergeSubsIntoGroup, d_data)
        for res in ff:
            f_command = f_command + '-O -GLOBAL_SHIFT AUTO  \"{tile}\\{file}\" '.format(tile=tile, file=res)

        QgsMessageLog.logMessage('Finished genearting {count} groups for tile {tile}'.format(count=len(d_data),tile=tile),CATEGORY,Qgis.Info)
        
        #Join groups into one file
        f_command = f_command + '-AUTO_SAVE OFF -MERGE_CLOUDS -C_EXPORT_FMT LAS -SAVE_CLOUDS FILE \"{tile}.las\"'.format(tile=tile)
        subprocess.check_output(f_command,cwd=download_dir, shell=True)
        sleep(1)
        QgsMessageLog.logMessage('Finished generating las for tile {tile}'.format(tile=tile), CATEGORY, Qgis.Info)

    

    if len(tiles) > 1:
        #Merge tiles into one las file, if there are more than one tiles
        c_command = '\"C:\\Program Files\\CloudCompare\\CloudCompare\" -SILENT '
        bottom = 0
        top = 0
        left = 0
        right = 0

        for tile in tiles:
            x = int(re.findall(r'([0-9][0-9][0-9])_',tile)[0])
            y = int(re.findall(r'_([0-9][0-9][0-9][0-9])',tile)[0])
            
            if bottom != 0:
                if y < bottom:
                    bottom = y
                if y > top:
                    top = y
                if x < left:
                    left = x
                if x > right:
                    right = x
            else:
                bottom = y
                top = y
                left = x
                right = x

            c_command = c_command + '-O -GLOBAL_SHIFT AUTO  \"{tile}.las\" '.format(tile=tile)


        QgsMessageLog.logMessage("left:{l} bottom:{b} right:{r} top:{t}".format(l=str(left),b=str(bottom),r=str(right),t=str(top)), CATEGORY, Qgis.Info)
        c_command = c_command + '-AUTO_SAVE OFF -MERGE_CLOUDS -C_EXPORT_FMT LAS -SAVE_CLOUDS FILE \"{left}_{bottom}_{right}_{top}_Merged.las\"'.format(left=str(left),bottom=str(bottom),right=str(right),top=str(top))
        subprocess.check_output(c_command,cwd=download_dir, shell=True)
        sleep(1)

        for tile in tiles:
            os.remove(os.path.join(download_dir, "{tile}.las".format(tile=tile)))
            sleep(0.5)

    return tiles

def downloadFile(data):
    r = requests.get(data[1],allow_redirects=True)
    with open(os.path.join(os.path.join(download_dir,data[2]), data[0]), 'wb') as fi:
        fi.write(r.content)
        fi.close()
    sleep(0.2)
    return data[0]

def mergeSubsIntoGroup(d_data):
    command = '\"C:\\Program Files\\CloudCompare\\CloudCompare\" -SILENT '
    for f in d_data[2]:
       command = command + '-O -GLOBAL_SHIFT AUTO  \"{tile}\\{file}\" '.format(tile=d_data[1], file=f)
    command = command + '-AUTO_SAVE OFF -MERGE_CLOUDS -C_EXPORT_FMT LAS -SAVE_CLOUDS FILE \"{tile}\\{file}.las\"'.format(tile=d_data[1],file=d_data[0])
    subprocess.check_output(command,cwd=download_dir, shell=True)
    sleep(1)
    return str(d_data[0]) + ".las"

def tileProccesed(task, tiles=None):
    if tiles is not None:
        QgsMessageLog.logMessage('Finished generating las for {tiles} tiles'.format(tiles=len(tiles)), CATEGORY, Qgis.Info)
        #Remove subfragemnts for tiles
        for tile in tiles:
            shutil.rmtree(os.path.join(download_dir, tile))
            sleep(0.5)

task = QgsTask.fromFunction('Generating las for {tiles} tile'.format(tiles=len(tiles)), downloadFiles, on_finished=tileProccesed, tiles=grid_tiles)
QgsApplication.taskManager().addTask(task)
