from qgis.core import QgsApplication
from .algorithms.arrival_time_calculator import ArrivalTimeCalculatorAlgorithm
from .Arrival_Time_Calculator_provider import ArrivalTimeCalculatorProvider
import sys
import os
import inspect

cmd_folder = os.path.split(inspect.getfile(inspect.currentframe()))[0]

if cmd_folder not in sys.path:
    sys.path.insert(0, cmd_folder)

class ArrivalTimeCalculator:
    def __init__(self, iface):
        self.iface = iface
        self.provider = ArrivalTimeCalculatorProvider()
        

    def initGui(self):
        QgsApplication.processingRegistry().addProvider(self.provider)

    def unload(self):
        QgsApplication.processingRegistry().removeProvider(self.provider)

    def run(self):
        # Пример вызова вашего алгоритма
        parameters = {
            'INPUT': 'C:\\Users\\mesla\\Documents\\Границы.gpkg|layername=Границы',  # Замените на ваш слой
            'OUTPUT': 'TEMPORARY_OUTPUT'  # Выходные параметры
        }
        algorithm = ArrivalTimeCalculatorAlgorithm()
        result = algorithm.processAlgorithm(parameters, None, None)
