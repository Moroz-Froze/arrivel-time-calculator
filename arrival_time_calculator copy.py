from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.core import (
    QgsProject,
    QgsProcessingException,
    QgsProcessingAlgorithm,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterMatrix,
    QgsProcessingParameterFileDestination,
    QgsField,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsVectorLayer,
    QgsProcessing,
    QgsProcessingParameterBoolean
)
from shapely.ops import unary_union
import osmnx as ox
import networkx as nx
from shapely.wkt import loads
from shapely.geometry import Polygon

class ArrivalTimeCalculatorAlgorithm(QgsProcessingAlgorithm):
    """
    Алгоритм для расчёта времени прибытия с использованием дорожной сети из OSM.
    """

    INPUT = 'INPUT'
    OUTPUT = 'OUTPUT'
    START_POINTS = 'START_POINTS'
    END_POINTS = 'END_POINTS'
    SPEEDS = 'SPEEDS'
    DISPLAY_ROUTES = 'DISPLAY_ROUTES'

    default_speed_limits = {
        "trunk":          53,
        "trunk_link":     53,
        "motorway":       53,
        "motorway_link":  53,
        "primary":        40,
        "primary_link":   40,
        "secondary":      40,
        "secondary_link": 40,
        "unclassified":   40,
        "tertiary":       28.1,
        "tertiary_link":  28.1,
        "residential":    28.1,
        "living_street":  28.1,
        "road":           17.3,
        "service":        17.3,
        "track":          17.3,
        "footway":        5.4,
        "path":           5.4,
        "pedestrian":     5.4,
        "steps":          5.4,
        "cycleway":       5.4,
        "bridleway":      5.4,
        "corridor":      5.4,
    }

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.INPUT,
            self.tr('Границы расчётов'),
            [QgsProcessing.TypeVectorPolygon]
        ))


        self.addParameter(QgsProcessingParameterBoolean(
            self.DISPLAY_ROUTES,
            self.tr('Отображение маршрута'),
            defaultValue=True  # По умолчанию маршруты отображаются
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
        # Проверка, включено ли отображение маршрутов
        display_routes = self.parameterAsBoolean(parameters, self.DISPLAY_ROUTES, context)

        feedback.pushInfo('Версия библиотек:')
        feedback.pushInfo(f'   osmnx: {ox.__version__}')
        feedback.pushInfo(f'   networkx: {nx.__version__}')

        # Получаем слой границ и проверяем его
        source = self.parameterAsSource(parameters, self.INPUT, context)
        if source is None:
            raise QgsProcessingException(self.invalidSourceError(parameters, self.INPUT))

        # Извлечение многоугольников и создание графа
        polygons = self.extract_polygons(source)
        G = self.load_graph_from_osm(polygons, feedback)
        if G is None or G.number_of_nodes() == 0:
            feedback.reportError("Граф не загружен или не содержит узлов.")
            return

        # Получаем стартовые и конечные точки
        start_points = list(self.parameterAsSource(parameters, self.START_POINTS, context).getFeatures())
        end_points = list(self.parameterAsSource(parameters, self.END_POINTS, context).getFeatures() if parameters[self.END_POINTS] else [])

        if not start_points:
            feedback.reportError("Начальные точки не указаны.")
            return

        speed_limits = self.load_speed_limits(self.parameterAsMatrix(parameters, self.SPEEDS, context))

        # Создаем слой маршрутов (если отображение включено)
        layer = None
        if display_routes:
            layer_name = 'Routes'
            layer = QgsVectorLayer('LineString?crs=EPSG:4326', layer_name, 'memory')
            provider = layer.dataProvider()

            provider.addAttributes([
                QgsField("Travel Time", QVariant.Double),  # Атрибут для времени
                QgsField("Start Name", QVariant.String),  # Имя начальной точки
                QgsField("End Name", QVariant.String)  # Имя конечной точки
            ])
            layer.updateFields()

        # Расчёт маршрутов
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
                    travel_time = self.calculate_travel_time(G, route, feedback, speed_limits)

                    feedback.pushInfo(f'Маршрут: {start_name} → {end_name}, Время: {travel_time:.2f} минут')

                    # Добавление маршрута в слой, если отображение включено
                    if display_routes:
                        self.display_route(layer, route, travel_time, start_name, end_name, G)

                except nx.NetworkXNoPath:
                    feedback.reportError(f"Маршрут между точками {start_name} и {end_name} не найден.")
                    continue

                route_count += 1
                feedback.setProgress(int((route_count / total_routes) * 100))

        # Добавляем слой с маршрутами на карту (если отображение включено)
        if display_routes and route_count > 0:
            layer.updateExtents()
            QgsProject.instance().addMapLayer(layer)
        elif route_count == 0:
            feedback.reportError("Маршруты не были рассчитаны.")

        return {self.OUTPUT: parameters[self.OUTPUT]}


    def display_route(self, layer, route, travel_time, start_name, end_name, G):
        coords = [(G.nodes[n]['x'], G.nodes[n]['y']) for n in route]
        geometry = QgsGeometry.fromPolylineXY([QgsPointXY(*coord) for coord in coords])

        feature = QgsFeature()
        feature.setGeometry(geometry)
        feature.setAttributes([travel_time, start_name, end_name])  # Set travel time, start and end names as attributes
        
        provider = layer.dataProvider()
        provider.addFeature(feature)
        layer.updateExtents()
        # Repaint the layer to reflect added features
        layer.triggerRepaint()

    def load_speed_limits(self, speed_matrix):
        speed_limits = self.default_speed_limits.copy()
        for row in speed_matrix:
            if isinstance(row, list) and len(row) >= 2:
                try:
                    road_type = str(row[0]).strip()
                    speed = float(row[1])
                    speed_limits[road_type] = speed
                except (ValueError, IndexError):
                    continue
        return speed_limits

    def load_graph_from_osm(self, polygons, feedback):
        feedback.pushInfo("Загрузка графа из OSM...")
        minx, miny, maxx, maxy = polygons.bounds
        polygon = Polygon([(minx, miny), (minx, maxy), (maxx, maxy), (maxx, miny)])
        graph = ox.graph_from_polygon(polygon, network_type='all')
        feedback.pushInfo("Граф успешно загружен.")
        return graph

    def get_speed(self, road_type, speed_limits):
        if isinstance(road_type, list):
            road_type = road_type[0]
        return speed_limits.get(road_type, 30)

    def calculate_travel_time(self, G, route, feedback, speed_limits):
        total_time = 0.0
        for i in range(len(route) - 1):
            edge_data = G.get_edge_data(route[i], route[i + 1])
            if edge_data:
                first_edge_key = next(iter(edge_data))
                road_type = edge_data[first_edge_key].get('highway', 'residential')
                distance = edge_data[first_edge_key].get('length', 0) / 1000

                if distance > 0:
                    speed = self.get_speed(road_type, speed_limits)
                    time_on_segment = (distance / speed) * 60
                    total_time += time_on_segment
                else:
                    pass
        return total_time

    def extract_polygons(self, source):
        wkt_strings = []
        for feature in source.getFeatures():
            wkt_strings.append(feature.geometry().asWkt())
        return unary_union([loads(wkt) for wkt in wkt_strings])

    def name(self):
        return 'fire_truck_arrival_time_calculator'

    def displayName(self):
        return "Fire Station Arrival Time Calculator"

    def group(self):
        return "Fire Response"

    def groupId(self):
        return 'fire_response'

    def createInstance(self):
        return ArrivalTimeCalculatorAlgorithm()
    
    def shortHelpString(self):
        return self.tr(
            '''
            Рассчитывает время прибытия  пожарных подразделений к указанным целевым точкам (или узлам графа)
            '''
        )
