Guide: Terra++ Custom Terrain from Malta CloudIsle 3D GRID LiDAR Data
=====================================================================

Warning
-------
This guide uses data from the airborne LIDAR survey conducted as part of the ERDF156 project on the 17th February 2012, therefore use it at your discretion. The data uses the [Aattribution-NonCommercial-NoDerivatives 4.0 International](https://creativecommons.org/licenses/by-nc-nd/4.0/legalcode) license and has [no limitations to public access](https://inspire.ec.europa.eu/metadata-codelist/LimitationsOnPublicAccess/noLimitations).

Introduction
------------

This guide is intended for those who wish to create a custom terrain dataset to use in Malta. The guide only shows you how to download and generate the DEM(digital elevation model), to be used in the main guide. For this guide to work, you will need to install CloudCompare with the modified qCSF plugin for CloudCompare. After you complete all the steps, follow the main guide, starting at step C. 

Guide
-----

A. CloudCompare & QGIS preparation
----------------------------------

- Follow step A in the [main guide](https://github.com/DavixDevelop/TerraLidar) but be sure to install the modified qCSF plugin

B. Generating dem files
-----------------------
### Downloading lidar data
![](https://raw.githubusercontent.com/DavixDevelop/TerraLidar/master/countries/Malta/images/geoportal.png "Malta Public Geoserver")
- First, open the [Malta Public Geoserver](http://geoserver.pa.org.mt/publicgeoserver) website
- Zoom to the desired area
- On the left side (Table of Contents) click on `CloudIsle 3D (Point Data 2012)`
- Then choose `Grid LiDAR Data`
- From the map, take a note of which tiles you wish to use `(ex 456_3972,456_3973,455_3972,455_3973)`
- Download the [downloader.py](https://raw.githubusercontent.com/DavixDevelop/TerraLidar/master/countries/Malta/downloader.py) script
- Open QGIS and navigate to `Plugins/Python Console` in the toolbar
- In the opened bottom panel click on the `Show Editor` button (Script icon)
- Open the downloader.py file using the `Open Script...` button (Folder icon)
- Once open, navigate to the `download_dir` line (line: 12)
- Here replace the path with the path where you wish to store the downloaded lidar data and make sure to use double backslash
- Navigate one line down (line: 13)
- Here, type in one or more noted tiles and make sure to use quotation marks and no comma at the end, like in the example
- Save the changes using the `Save` button (Floppy disk icon)
- Navigate to `View/Panels/Log Messages` in the toolbar
- Now, depending on how many tiles you wish to download, this can take quite a while. Click on the `Run Script` button (green play button)
- After the script is finished you will get a notification from QGIS

### Generating raster data
- Download the [export_dem_malta.py](https://raw.githubusercontent.com/DavixDevelop/TerraLidar/master/countries/Malta/export_dem_malta.py) script
- Open the `export_dem_malta.py` file using the `Open Script...` button (Folder icon)
- Once open navigate to the `source_directory` line (line: 14)
- Here replace the path with your path to the folder where you saved the lidar data (`downlaod_dir` in the previous step) and make sure to use double backslash
- Then navigate to the `dem_directory` line (line: 15) and replace the path where you wish to save the dem files, making sure to use double backslash
- Save the changes using the `Save` button (Floppy disk icon)
- Now, depending on the size of the area, this can take quite a while. Click on the `Run Script` button (green play button)
- After the script is finished you will get a notification from QGIS

C. Importing dem files
----------------------
- From here on forward, follow the [main guide](https://github.com/DavixDevelop/TerraLidar), starting at step C, but be sure to use `EPSG:23033` as the crs for the imported layer and when asked which transformation to use in the `Select Transformation` window, select the one that has an area of use: `World - N hemisphere - 12°E to 18°E, Malta - onshore` (9th one)