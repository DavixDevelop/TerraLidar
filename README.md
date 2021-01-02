Guide: Terra++ Custom Terrain from Lidar data
=============================================

Warning
-------
I do not own the provided qCSF plugin, therefore use it at your discretion. You may use the provide compiled dynamic library file or you may compile it from the source in the plugins folder.

Introduction
------------

This guide is intended for those who wish to use the custom terrain feature for the mod Terra++ for Minecraft and wish to use lidar/raster data as the data source. The following procedure takes quite a while, but this is the nature when working with lidar data. It's also presumed that if you use lidar data, that the data hasn't been processed before (for example, the off-ground points removed, with ground points remaining). If your lidar data only has ground points, use the ground_only_export_dem.py script instead or if your source data is raster data, use convert_dem.py script instead. The guide has been tested with CloudCompare v2.11.1 and QGIS v3.14.1.

Short description
-----------------

The following procedure first converts your lidar/source files to dem, then it imports the generated files, converts them into a suitable format for Terra++ mod and at the end splits them into tiles.

Guide
-----

A. CloudCompare & QGIS preparation
----------------------------------

- First download and install CloudComapre v2.11 from [here](https://www.danielgm.net/cc) [Note: You can skip this if you will use the convert_dem script only]
- Download and install the latest version of QGIS in [OSGeo4W](https://qgis.org/en/site/forusers/download.html)
- Download the [QCSF_PLUGIN.dll](https://github.com/DavixDevelop/TerraLidar/raw/master/qCSF/QCSF_PLUGIN.dll) file from the qCSF folder on this repository or build it on your own from the source in the plugins folder. More on that [here](https://github.com/CloudCompare/CloudCompare). Then place the plugin in the plugins folder (default: C:\Program Files\CloudCompare\plugins) [Note: You can skip this if you will use the ground_only_export_dem script or the convert_dem script only]

B. Generating dem files
-----------------------
- Download and place your lidar/source files into a folder (ex. Documents\Minecraft\Source)
- Open QGIS and navigate to Plugins/Python Console in the toolbar
- In the opened bottom panel click on the "Show Editor" button (Script icon)
- Open the export_dem.py (if your lidar data doesn't contain only ground points), ground_only_export_dem.py (if your lidar data only contains ground points) or convert_dem.py (if your source data is raster data) file using the "Open Script..." button (Folder icon)
- Once open navigate to the source_directory line (line: 14)
- Here replace the path with your path to the folder where you lidar/source data is saved and make sure to use double backslash
- Then navigate to the dem_directory line (line: 15) and replace the path where you wish to save the dem files, making sure to use double backslash
- Save the changes using the "Save" button (Floppy disk icon)
- Navigate to View/Panels/Log Messages in the toolbar
- Now, depending on how many lidar/source files you have this can take quite a while, up to multiple hours if you use the export_dem script. Click on the "Run Script" button (green play button)
- After the script is finished you will get a notification from QGIS

C. Importing dem files
----------------------
- Close the previous script and open the loadraster_folder.py file in QGIS Python Console
- Double click on OpenStreetMap in the left panel
- Navigate to the file_directory line (line: 65)
- Here replace the path with your path to the folder where your .tif files are located
- Save the script and run it
- It may lag a bit at the start and the end but let it run. Again, this can take a while
- The script outputs the progress into the Log Messages panel
- Once It's done QGIS will send you a notification

D. Setting up the project
-------------------------
- Select all your imported layers in the left and right-click on them
- Navigate to Set CRS/Set Layer CRS...
- In the opened window choose the same coordinate reference system your lidar/source dataset uses (ex. Slovenia 1996 / Slovene National Grid). If you have problems with this step, select the layer, go to Layers/Save as, set the CRS, save the file/files and repeat the C section.
- Click OK
- In the bottom right corner click the current project coordinate reference system (ex EPSG...)
- In the opened windows search for EPSG:4326 (WGS 84)
- Click on WGS 84 and click OK
- Make sure the layers are in the right location over the map

E. QMetaTiles plugin
--------------------
- Navigate to Plugins/Manage And Install Plugins... in the toolbar
- In the opened window click on All and search for QMetaTiles
- Click on the result and install it
- Close the window

F. Generating tiles
-------------------
- Delete the OpenStreetMap layer
- Navigate to Plugins/QMetaTiles/QMetaTiles
- Set the Tileset name and choose the Output Directory (Documents\Minecraft\CustomTerrain)
- Select Full extent (Make sure the OpenStreetMap layer is deleted)
- Set the Minimum and Maximum zoom to 17, or lower depending on the resolution of your data, or if you want the dataset to use less space
- Disable Metatiling
- Set the Quality under Parameters to 100
- Select "Make lines appear less jagged at the expense of some drawing performance"
- Make sure that the format is set to PNG
- Click OK
- This will take quite a while depending on how a large area you have
- Once It's finished you can close QGIS

G. Minecraft Terra++
--------------------
- Download and install Terra++ from [here](https://github.com/BuildTheEarth/terraplusplus/releases/tag/jenkins)
- Open Minecraft and create a new world using the usual Build The Earth settings
- Set the Custom Terrain to ON
- In the Custom Terrain Directory textbox, specify the path to your tile, but be sure to use / instead of \ and add a / at the end (ex. C:/Users/david/Documents/Minecraft/CustomTerrain/Flats/)
- Once the world loads navigate to your location using the /tpll command and it should load your custom terrain

qCSF plugin
-----------

The provided plugin is a modified version of the qCSF plugin made to work in the command mode. It will be included in the future release of CloudComapre (v2.12). If you wish to learn more go [here](https://github.com/DavixDevelop/TerraLidar/tree/master/qCSF).