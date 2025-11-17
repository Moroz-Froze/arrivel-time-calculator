"""
Провайдер алгоритмов обработки для анализа времени прибытия пожарных подразделений
"""

from qgis.core import QgsProcessingProvider
from qgis.PyQt.QtGui import QIcon
import os

from .algorithms.nearest_fire_station_algorithm import NearestFireStationAlgorithm
from .algorithms.response_time_routes_algorithm import ResponseTimeRoutesAlgorithm
from .algorithms.all_stations_response_algorithm import AllStationsResponseAlgorithm


class FireResponseAnalysisProvider(QgsProcessingProvider):
    """Провайдер алгоритмов для анализа пожарных подразделений"""

    def __init__(self):
        super().__init__()

    def id(self):
        """Уникальный идентификатор провайдера"""
        return 'fire_response_analysis'

    def name(self):
        """Название провайдера"""
        return 'Fire Response Time Analysis'

    def icon(self):
        """Иконка провайдера"""
        return QIcon(os.path.join(os.path.dirname(__file__), 'icons', 'icon.png'))

    def longName(self):
        """Полное название провайдера"""
        return 'Fire Response Time Analysis'

    def loadAlgorithms(self):
        """Загрузка всех алгоритмов"""
        self.addAlgorithm(NearestFireStationAlgorithm())
        self.addAlgorithm(ResponseTimeRoutesAlgorithm())
        self.addAlgorithm(AllStationsResponseAlgorithm())

    def supportedOutputTableExtensions(self):
        """Поддерживаемые форматы таблиц"""
        return ['csv', 'xlsx']

    def supportedOutputRasterLayerExtensions(self):
        """Поддерживаемые форматы растровых слоев"""
        return ['tif', 'tiff']

    def supportedOutputVectorLayerExtensions(self):
        """Поддерживаемые форматы векторных слоев"""
        return ['shp', 'gpkg', 'geojson', 'kml']
