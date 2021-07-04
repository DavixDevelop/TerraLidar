import math
import glob
import os
import sys
from osgeo import gdal
from osgeo import gdalconst
from qgis.utils import iface
from qgis.core import QgsProject
from time import sleep
import numpy as np
from datetime import datetime
from ftplib import FTP_TLS
from ftplib import FTP

gdal.UseExceptions()

CATEGORY = 'CreateRegionsImage'

region2d_folder = 'C:/Users/david/AppData/Roaming/.minecraft/saves/BTE Celje/region2d' #Set it to the path of the save region2d folder
output_file = 'C:/Users/david/Documents/Minecraft/Celje.png' #Set it to the path of the ouptut png image that will be created

scale = 1.0 #Set the scaling (ex 1.0 means 1 pixel=1region, 0.5 means 1 pixel=4 regions)


top_x = 7000 #Top left corner x
top_z = -9900 #Top left corner z
bottom_x = 8599 #Bottom right corner x
bottom_z = -8901 #Bottom right corner z


scan_allfiles = False #Set it to True, to create an image out of all region2d files

ftp_scan = False # Set to True to scan for region2d files on the FTP server. Else, leave at False
ftp_s = False # Set to True, if you use a FTPS server
ftp_url = '' # FTP url (Only IP address or domain, ex 192.168.0.26)
ftp_port = 21 # FTP port, ex. 2121. Must be set
#Path to the region2d folder on the FTP server , ex. 'world/region2d'. Leave at None if the region2d files are on the root
ftp_region2d_folder = None
ftp_user = None # Leave at None for anonymous login, else set to user name, ex. 'davix'
ftp_password = None # Leave at None for anonymous login, else set to user password, ex. 'password'

IS_REGION_FILENAME = re.compile(r'^(-?(?:\d+,?)+)\.(-?(?:\d+,?)+)')
IS_REGION_FILE = re.compile(r'^(-?(?:\d+,?)+)\.(-?(?:\d+,?)+).2dr')

class Region:
    def __init__(self, x, z):
        self.x = x
        self.z = z

class Bounds:
    def __init__(self, minX, minZ, maxX, maxZ):
        self.minX = minX
        self.minZ = minZ
        self.maxX = maxX
        self.maxZ = maxZ

def writeRow(dst_src, red, green, blue, alpha, row):
    dst_src.GetRasterBand(1).WriteArray(red, yoff=row)
    dst_src.FlushCache()
    dst_src.GetRasterBand(2).WriteArray(green, yoff=row)
    dst_src.FlushCache()
    dst_src.GetRasterBand(3).WriteArray(blue, yoff=row)
    dst_src.FlushCache()
    dst_src.GetRasterBand(4).WriteArray(alpha, yoff=row)
    dst_src.FlushCache()

def genImage(task, bound):
    time_start = datetime.now()
    try:
        regions = []
        if not ftp_scan:
            raw_files = os.listdir(region2d_folder)
            for raw_file in raw_files:
                if raw_file.endswith(".2dr"):
                    fl = os.path.join(region2d_folder, raw_file).replace("\\","/")
                    fileinfo = QFileInfo(fl)
                    filename = fileinfo.completeBaseName()
                    m = IS_REGION_FILENAME.match(filename)
                    if m:
                        x = int(m.group(1))
                        z = int(m.group(2))
                        regions.append(Region(x,z))
        else:
            try:
                ftp = None
                if ftp_s:
                    ftp = FTP_TLS()
                else:
                    ftp = FTP()
                ftp.connect(ftp_url, ftp_port)
                if ftp_user is None or ftp_password is None:
                    ftp.login()
                else:
                    ftp.login(user=ftp_user, passwd=ftp_password)

                if ftp_region2d_folder is not None:
                    try:
                        ftp.cwd(ftp_region2d_folder)
                    except:
                        QgsMessageLog.logMessage('Error: Path does not exist on FTP server', CATEGORY, Qgis.Info)
                        return None

                remote_files = ftp.nlst()

                for rf in remote_files:
                    m = IS_REGION_FILE.match(rf)
                    if m:
                        x = int(m.group(1))
                        z = int(m.group(2))
                        regions.append(Region(x,z))
                ftp.quit()

            except Exception as e:
                QgsMessageLog.logMessage('No 2dr files found or wrong ftp options. Error: ' + str(e), CATEGORY, Qgis.Info)
                return None

        if scan_allfiles:
            if(len(regions) > 0):
                bound.minX = min(regions, key=lambda e: e.x).x
                bound.minZ = min(regions, key=lambda e: e.z).z
                bound.maxX = max(regions, key=lambda e: e.x).x
                bound.maxZ = max(regions, key=lambda e: e.z).z
                QgsMessageLog.logMessage('Bounds set to Top({top_x}, {top_z}), Bottom({bottom_x}, {bottom_z})'.format(top_x=str(bound.minX),top_z=str(bound.minZ),bottom_x=str(bound.maxX),bottom_z=str(bound.maxZ)), CATEGORY, Qgis.Info)
            else:
                QgsMessageLog.logMessage('No 2dr files found', CATEGORY, Qgis.Info)
                return None
        else:
            temp_regions = regions
            regions = []
            for reg in temp_regions:
                if reg.x >= bound.minX and reg.x <= bound.maxX and reg.z >= bound.minZ and reg.z <= bound.maxZ:
                    regions.append(reg)

            temp_regions = None

        if len(regions) == 0:
            QgsMessageLog.logMessage('No 2dr files found', CATEGORY, Qgis.Info)
            return None

        range_width = abs(bound.maxX - bound.minX) + 1
        range_height = abs(bound.minZ - bound.maxZ) + 1

        width = int(round(range_width * scale))
        height = int(round(range_height * scale))

        temp_file = output_file + ".tif"

        red = np.zeros(shape=(1,width), dtype=np.byte)
        green = np.zeros(shape=(1,width), dtype=np.byte)
        blue = np.zeros(shape=(1,width), dtype=np.byte)
        alpha = np.zeros(shape=(1,width), dtype=np.byte)

        regions.sort(key = lambda ee: ee.z)

        out_driver = gdal.GetDriverByName('GTiff')
        dst_src = out_driver.Create(temp_file, width, height, 4, gdal.GDT_Byte)

        cf = height
        rt = 0

        #Write empty rows
        for tty in range(0, height):
            writeRow(dst_src, red, green, blue, alpha, tty)
            rt += 1
            task.setProgress(max(0, min(int(((rt * 50) / cf)), 100)))

        rc = 0
        cc = len(regions)

        y = None

        t_width = width - (1 * scale)
        t_height = height - (1 * scale)
        t_range_width = range_width - 1
        t_range_height = (range_height - 1)

        for reg in regions:
            coord_x = reg.x - bound.minX
            coord_y = reg.z - bound.minZ

            x = max(0, min(int(round((coord_x * t_width) / t_range_width)), width - 1))
            y = max(0, min(int(round((coord_y * t_height) / t_range_height)), height - 1))

            red = dst_src.GetRasterBand(1).ReadAsArray(yoff=y,win_xsize=width, win_ysize=1)
            green = dst_src.GetRasterBand(2).ReadAsArray(yoff=y,win_xsize=width, win_ysize=1)
            blue = dst_src.GetRasterBand(3).ReadAsArray(yoff=y,win_xsize=width, win_ysize=1)
            alpha = dst_src.GetRasterBand(4).ReadAsArray(yoff=y,win_xsize=width, win_ysize=1)

            red[0][x] = 199
            green[0][x] = 144
            blue[0][x] = 185
            alpha[0][x] = 255
            writeRow(dst_src, red, green, blue, alpha, y)
            rc += 1
            task.setProgress(max(0, min(int((rc * 50) / cc) + 50, 100)))

        #Save copy
        QgsMessageLog.logMessage('Creating a PNG copy. This might take a while', CATEGORY, Qgis.Info)
        #gdal.GetDriverByName('PNG').CreateCopy(output_file, clip_ras)
        gdal.Translate(output_file, dst_src, options=["ZLEVEL=9"], format="PNG")

        dst_src = None

        os.remove(temp_file)
        sleep(0.05)

        return time_start
    except Exception as e:
        QgsMessageLog.logMessage('Error: ' + str(e), CATEGORY, Qgis.Info)
        return None

def imageGenerated(task, res=None):
    if res is not None:
        time_end = datetime.now()
        eclipsed = (time_end - res).total_seconds() / 60.0
        minutes = math.floor(eclipsed)
        seconds = math.floor((eclipsed - minutes) * 60)
        QgsMessageLog.logMessage('Done creating image in {minutes} minutes and {seconds} seconds'.format(minutes=minutes, seconds=seconds), CATEGORY, Qgis.Info)

task = QgsTask.fromFunction('Create region image', genImage, on_finished=imageGenerated, bound=Bounds(top_x, top_z, bottom_x, bottom_z))
QgsApplication.taskManager().addTask(task)
