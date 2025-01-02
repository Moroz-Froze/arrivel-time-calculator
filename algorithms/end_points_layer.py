from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (
    QgsProject,
    QgsProcessingException,
    QgsProcessingAlgorithm,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterMatrix,
    QgsProcessingParameterFileDestination,
    QgsProcessing,
    QgsGeometry,
    QgsPointXY,
    QgsFeature
)
import osmnx as ox
import networkx as nx
from . .utils.speed_management import SpeedManager
from . .utils.osm_utils import load_graph_from_osm
from . .utils.geometry_utils import extract_polygons, calculate_travel_time
from . .utils.layer_management import create_point_layer, display_point


class EndPointsLayerAlgorithm(QgsProcessingAlgorithm):
    """
    Алгоритм для создания слоя конечных точек.
    """

    INPUT = 'INPUT'
    OUTPUT = 'OUTPUT'
    START_POINTS = 'START_POINTS'
    END_POINTS = 'END_POINTS'
    SPEEDS = 'SPEEDS'

    default_speed_limits = SpeedManager.default_speed_limits

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.INPUT,
            self.tr('Границы расчётов'),
            [QgsProcessing.TypeVectorPolygon]
        ))

        self.addParameter(QgsProcessingParameterFileDestination(
            self.OUTPUT,
            self.tr('Output File'),
            'Geopackage file (*.gpkg)',
        ))

        self.addParameter(QgsProcessingParameterFeatureSource(
            self.START_POINTS, self.tr('Местоположение пожарного подразделения'), [QgsProcessing.TypeVectorPoint, QgsProcessing.TypeVectorPolygon],
        ))

        self.addParameter(QgsProcessingParameterFeatureSource(
            self.END_POINTS, self.tr('Конечные точки'),
            [QgsProcessing.TypeVectorPoint, QgsProcessing.TypeVectorPolygon],
            optional=True,
        ))

        self.addParameter(
            QgsProcessingParameterMatrix(
                self.SPEEDS,
                self.tr('Follow-up Speeds'),
                numberRows=5,
                hasFixedNumberRows=True,
                headers=[self.tr('Road Type'), self.tr('Speed')],
                defaultValue=[
                    'Городские магистрали и улицы общегородского значения', 49,
                    'Магистральные улицы районного значения', 37,
                    'Улицы и дороги местного назначения', 26,
                    'Служебные проезды.', 16,
                    'Пешеходные зоны и территории, пригодные для передвижения пожарных автомобилей', 5
                ]
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        feedback.pushInfo('Версии библиотек:')
        feedback.pushInfo(f'   osmnx: {ox.__version__}')
        feedback.pushInfo(f'   networkx: {nx.__version__}')

        # Получение параметров
        source = self.parameterAsSource(parameters, self.INPUT, context)
        if source is None:
            raise QgsProcessingException(self.invalidSourceError(parameters, self.INPUT))
        start_points = list(self.parameterAsSource(parameters, self.START_POINTS, context).getFeatures())
        end_points = list(self.parameterAsSource(parameters, self.END_POINTS, context).getFeatures() if parameters[self.END_POINTS] else [])
        speed_matrix = self.parameterAsMatrix(parameters, self.SPEEDS, context)


        if not start_points:
            raise QgsProcessingException("Начальные точки не указаны.")

        polygons = extract_polygons(source)
        G = load_graph_from_osm(polygons, feedback)
        if G is None or G.number_of_nodes() == 0:
            raise QgsProcessingException("Граф не загружен или не содержит узлов.")

        speed_manager = SpeedManager()
        speed_limits = speed_manager.load_speed_limits(speed_matrix)

        layer = create_point_layer()

        total_routes = len(start_points) * len(end_points)
        route_count = 0

        for start_feature in start_points:
            start_x, start_y = start_feature.geometry().asPoint().x(), start_feature.geometry().asPoint().y()
            start_name = start_feature.attribute('name') if start_feature.attribute('name') else 'Unknown'

            for end_feature in end_points:
                end_x, end_y = end_feature.geometry().asPoint().x(), end_feature.geometry().asPoint().y()
                end_name = end_feature.attribute('name') if end_feature.attribute('name') else 'Unknown'

                try:
                    start_node = ox.distance.nearest_nodes(G, start_x, start_y)
                    end_node = ox.distance.nearest_nodes(G, end_x, end_y)
                    route = nx.shortest_path(G, start_node, end_node, weight='length')
                    travel_time = calculate_travel_time(G, route, speed_limits)

                    feedback.pushInfo(f'Маршрут: {start_name} → {end_name}, Время: {travel_time:.2f} минут')
                    end_point_geometry = QgsGeometry.fromPointXY(QgsPointXY(end_x, end_y))
                    display_point(layer, end_point_geometry, travel_time, start_name, end_name)

                except nx.NetworkXNoPath:
                    feedback.reportError(f"Маршрут между точками {start_name} и {end_name} не найден.")
                    continue

                route_count += 1
                feedback.setProgress(int((route_count / total_routes) * 100))

        layer.updateExtents()
        QgsProject.instance().addMapLayer(layer)

        return {self.OUTPUT: parameters[self.OUTPUT]}


    def name(self):
        return 'end_points_layer_creator'

    def displayName(self):
        return "Генератор слоя конечных точек"

    def group(self):
        return "Оценка реагирования сил и средств пожарной охраны"

    def groupId(self):
        return 'fire_response'

    def createInstance(self):
        return EndPointsLayerAlgorithm()

    def shortHelpString(self):
        return self.tr(
            '''
            Создает слой конечных точек для дальнейшей обработки и анализа.
            '''
        )