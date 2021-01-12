Guide: Terra++ Custom Terrain from Malta CloudIsle 3D GRID LiDAR Data
=====================================================================

Warning
-------
This guide uses data from DMR1, which was derived from pre-processed Lidar, which contains only the terrain at 1m resolution, 1200m-1400m over Slovenia, therefore use it at your discretion. The data is licensed under [Creative Commons 4.0](https://creativecommons.org/licenses/by/4.0/deed.sl).

> Use Limitations:
> General conditions for the use of geodetic data: https://www.e-prostor.gov.si/dostop-do-podatkov/dostop-do-podatkov/#tab1-1029
>
> Public access Restrictions:
> No restrictions

Attribution statement:

> Geodetska uprava Republike Slovenije, LiDAR, DMR1 2015
> © 2017 MOP - Geodetska uprava Republike Slovenije - Vse pravice pridržane.

Introduction
------------

This guide is intended for those who wish to create a custom terrain dataset to use in Slovenia. This guide only shows you how to download and convert the individual tiles to DEM(digital elevation model), to be used in the main guide. If you wish to use a larger area, you can use the [Joerd](https://github.com/DavixDevelop/joerd/tree/Slovenia_lidar_dataset) command-line tool. For this guide to work, you don't need to install CloudCompare.After you complete all the steps, follow the main guide, starting at step C. 

Guide
-----

A. CloudCompare & QGIS preparation
----------------------------------

- Follow step A in the [main guide](https://github.com/DavixDevelop/TerraLidar) but, you only need to install QGIS.

B. Generating dem files
-----------------------
### Downloading the data
![](https://raw.githubusercontent.com/DavixDevelop/TerraLidar/master/countries/Slovenia/images/gis_arso.png "Malta Public Geoserver")
- First, open the [Lidar GIS viewer](https://github.com/DavixDevelop/joerd/tree/Slovenia_lidar_dataset) website
- On the right side (Layers) click on `Lidar data fishnet in D96TM projection`
- Zoom to the desired area
- From the map, click on the desired tile (ex 519_121)
- In the opened tooltip, click on Data `download DTM (D96TM)` and download the file to a folder, where you wish to store the downloaded data
- Repeat this, for each desired tile

### Generating raster data
- Download the [convert_dmr1.py](https://raw.githubusercontent.com/DavixDevelop/TerraLidar/master/countries/Slovenia/convert_dmr1.py) script
- Open QGIS and navigate to `Plugins/Python Console` in the toolbar
- In the opened bottom panel click on the `Show Editor` button (Script icon)
- Open the `convert_dmr1.py` file using the `Open Script...` button (Folder icon)
- Once open navigate to the `source_directory` line (line: 14)
- Here replace the path with your path to the folder where you saved the files from the previous step and make sure to use double backslash
- Then navigate to the `dem_directory` line (line: 15) and replace the path where you wish to save the dem files, making sure to use double backslash
- Save the changes using the `Save` button (Floppy disk icon)
- Now, depending on the size of the area, this can take quite a while. Click on the `Run Script` button (green play button)
- After the script is finished you will get a notification from QGIS

> Note: If you used [Joerd](https://github.com/DavixDevelop/joerd/tree/Slovenia_lidar_dataset) to get the DEM, you can skip step B. You can then find the files in `/joerd/source/dmr1`

C. Importing dem files
----------------------
- From here on forward, follow the [main guide](https://github.com/DavixDevelop/TerraLidar), starting at step C. If imported correctly, you should not need to set the crs for the imported layer/s, but if didn't, set the layer crs to `EPSG:3794`