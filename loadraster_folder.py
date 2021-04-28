import math
import os
import multiprocessing
import concurrent.futures
from time import sleep
from qgis.utils import iface
from qgis.core import QgsProject


CATEGORY = 'ImportDem'

def newitem(altitude):
	red = math.floor(altitude/256) + 128
	remainder = altitude%256
	green = math.floor(remainder)
	remainder = remainder%1
	blue = math.floor(remainder*256)
	newitem = QgsColorRampShader.ColorRampItem(altitude, QColor(red, green, blue))
	return newitem

def processLayers(task, layers):
	QgsMessageLog.logMessage(
				'Started processing {count} layers'.format(count=len(layers)),
				CATEGORY, Qgis.Info)
	renders = []
	cpu_count = multiprocessing.cpu_count()
	ex = concurrent.futures.ThreadPoolExecutor(max_workers=cpu_count)
	f = ex.map(processLayer, layers)
	p = 0
	for res in f:
		renders.append(res)
		QgsMessageLog.logMessage(
				'Processed layer {name}'.format(name=res[2]),
				CATEGORY, Qgis.Info)
		p += 1
		task.setProgress(int((p * 100) / len(layers)))
		sleep(0.05)
	return renders

def layersCompleted(exception, result=None):
	if result is not None:
		for render in result:
			render[1].setRenderer(render[0])
			QgsMessageLog.logMessage(
				'Updated layer {name}'.format(name=render[2]),
				CATEGORY, Qgis.Info)
			sleep(0.05)

def processLayer(layer):
	rlayer = layer[0]
	stats = rlayer.dataProvider().bandStatistics(1, QgsRasterBandStats.All)
	min = int(math.floor(stats.minimumValue))
	max = int(math.ceil(stats.maximumValue))
	lst = []
	for meters in range(min, max):
		for fraction in range (0, 256):
			lst.append(newitem(meters+(fraction/256)))
	fnc = QgsColorRampShader()
	fnc.setColorRampType(QgsColorRampShader.Discrete)
	fnc.setColorRampItemList(lst)
	shader = QgsRasterShader()
	shader.setRasterShaderFunction(fnc)
	renderer = QgsSingleBandPseudoColorRenderer(rlayer.dataProvider(), 1, shader)
	return [renderer, rlayer, layer[1]]



file_directory = 'C:\\Users\\david\\Documents\\Minecraft\\TerDem' #enter file directory to load

files = os.listdir(file_directory)

new_layers = []

for dem in files:
	if (dem.endswith(".tif")) or (dem.endswith('.TIF')):
		fn = os.path.join(file_directory, dem)
		fileinfo = QFileInfo(fn)
		filename = fileinfo.completeBaseName()
		newlayer = iface.addRasterLayer(fn, filename)
		sleep(0.05)
		new_layers.append([newlayer, filename])
		sleep(0.05)
		QgsMessageLog.logMessage(
			'Added layer for {layername}'.format(layername=filename),
			CATEGORY, Qgis.Info)
		sleep(0.05)

QgsMessageLog.logMessage(
			'Found {count} dem files'.format(count=len(new_layers)),
			CATEGORY, Qgis.Info)

process_task = QgsTask.fromFunction('Finished importing dems', processLayers, on_finished=layersCompleted, layers=new_layers)
QgsApplication.taskManager().addTask(process_task)
