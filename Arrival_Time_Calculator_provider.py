__author__ = 'SPAA'
__date__ = '2024-12-16'
__copyright__ = '(C) 2024 by SPAA'

from qgis.core import QgsProcessingProvider
from .algorithms.arrival_time_calculator import ArrivalTimeCalculatorAlgorithm
from .algorithms.end_points_layer import EndPointsLayerAlgorithm

class ArrivalTimeCalculatorProvider(QgsProcessingProvider):

    def __init__(self):
        super().__init__()

    def loadAlgorithms(self):
        self.addAlgorithm(ArrivalTimeCalculatorAlgorithm())
        self.addAlgorithm(EndPointsLayerAlgorithm())

    def id(self):
        return 'arrival_time_calculator_provider'

    def name(self):
        return self.tr('Arrival Time Calculator')

    def icon(self):
        return QgsProcessingProvider.icon(self)

    def longName(self):
        return self.name()
