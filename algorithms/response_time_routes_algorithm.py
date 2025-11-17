"""
Алгоритм для создания векторного слоя маршрутов времени прибытия
"""

from qgis.core import (QgsProcessingAlgorithm, QgsProcessingParameterVectorLayer,
                       QgsProcessingParameterField, QgsProcessingParameterNumber,
                       QgsProcessingParameterFeatureSink, QgsProcessingParameterEnum,
                       QgsFeature, QgsGeometry, QgsPointXY,
                       QgsDistanceArea, QgsProject, QgsUnitTypes, QgsProcessingException,
                       QgsField, QgsFields, QgsWkbTypes, QgsProcessing)
from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.PyQt.QtGui import QIcon
import math
import importlib
import os

from ..graph_utils import (
    build_graph_for_layers,
    set_graph_travel_times,
    kmh_to_mm,
    DEFAULT_SPEEDS_KMH,
)


class ResponseTimeRoutesAlgorithm(QgsProcessingAlgorithm):
    """
    Алгоритм для создания векторного слоя маршрутов времени прибытия
    между объектами и пожарными подразделениями
    """

    # Константы параметров
    OBJECTS_LAYER = 'OBJECTS_LAYER'
    FIRE_STATIONS_LAYER = 'FIRE_STATIONS_LAYER'
    ROAD_SPEEDS_KMH = 'ROAD_SPEEDS_KMH'
    ROUTE_TYPE = 'ROUTE_TYPE'
    TIME_THRESHOLD = 'TIME_THRESHOLD'
    OUTPUT_LAYER = 'OUTPUT_LAYER'

    def tr(self, string):
        """Перевод строки"""
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        """Создание экземпляра алгоритма"""
        return ResponseTimeRoutesAlgorithm()

    def name(self):
        """Имя алгоритма"""
        return 'response_time_routes'

    def displayName(self):
        """Отображаемое имя алгоритма"""
        return self.tr('Маршруты времени прибытия')

    def icon(self):
        """Иконка алгоритма для панели инструментов Processing"""
        plugin_root = os.path.dirname(os.path.dirname(__file__))
        return QIcon(os.path.join(plugin_root, 'icons', 'response_time_routes_algorithm_icon.png'))

    def group(self):
        """Группа алгоритма"""
        return self.tr('Fire Response Analysis')

    def groupId(self):
        """ID группы алгоритма"""
        return 'fire_response_analysis'

    def shortHelpString(self):
        """Краткая справка"""
        return self.tr(
            "Этот алгоритм создает векторный слой маршрутов времени прибытия "
            "между объектами и пожарными подразделениями."
        )

    def initAlgorithm(self, config=None):
        """Инициализация параметров алгоритма"""
        
        # Входной слой объектов
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.OBJECTS_LAYER,
                self.tr('Слой объектов'),
                [QgsProcessing.TypeVectorPoint, QgsProcessing.TypeVectorPolygon]
            )
        )

        # Входной слой пожарных подразделений
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.FIRE_STATIONS_LAYER,
                self.tr('Слой пожарных подразделений'),
                [QgsProcessing.TypeVectorPoint]
            )
        )

        # Поле с названием подразделения определяется автоматически при выполнении

        # Средняя скорость движения (км/ч)
        # Скорости по типам дорог приходят списком из 5 значений (км/ч) из диалога

        # Тип маршрутов
        self.addParameter(
            QgsProcessingParameterEnum(
                self.ROUTE_TYPE,
                self.tr('Тип маршрутов'),
                options=[self.tr('Только к ближайшей станции'),
                        self.tr('Ко всем станциям'),
                        self.tr('Ко всем станциям в радиусе времени')],
                defaultValue=0
            )
        )

        # Пороговое время для фильтрации (минуты)
        self.addParameter(
            QgsProcessingParameterNumber(
                self.TIME_THRESHOLD,
                self.tr('Пороговое время прибытия (минуты)'),
                type=QgsProcessingParameterNumber.Double,
                minValue=1.0,
                maxValue=300.0,
                defaultValue=30.0,
                optional=True
            )
        )

        # Выходной слой
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT_LAYER,
                self.tr('Выходной слой маршрутов')
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        """Основная логика обработки"""
        
        # Получение параметров
        objects_layer = self.parameterAsVectorLayer(parameters, self.OBJECTS_LAYER, context)
        fire_stations_layer = self.parameterAsVectorLayer(parameters, self.FIRE_STATIONS_LAYER, context)
        speeds_kmh = parameters.get(self.ROAD_SPEEDS_KMH, DEFAULT_SPEEDS_KMH)
        if not isinstance(speeds_kmh, list) or len(speeds_kmh) != 5:
            speeds_kmh = DEFAULT_SPEEDS_KMH
        route_type = self.parameterAsInt(parameters, self.ROUTE_TYPE, context)
        time_threshold = self.parameterAsDouble(parameters, self.TIME_THRESHOLD, context)

        if objects_layer is None:
            raise QgsProcessingException(self.invalidSourceError(parameters, self.OBJECTS_LAYER))
        
        if fire_stations_layer is None:
            raise QgsProcessingException(self.invalidSourceError(parameters, self.FIRE_STATIONS_LAYER))

        # Создание полей выходного слоя
        fields = QgsFields()
        fields.append(QgsField('object_id', QVariant.Int))
        fields.append(QgsField('station_name', QVariant.String))
        fields.append(QgsField('distance_km', QVariant.Double))
        fields.append(QgsField('response_time_min', QVariant.Double))
        fields.append(QgsField('object_type', QVariant.String))
        fields.append(QgsField('route_type', QVariant.String))

        (sink, dest_id) = self.parameterAsSink(
            parameters, self.OUTPUT_LAYER, context,
            fields, QgsWkbTypes.LineString, objects_layer.sourceCrs()
        )

        if sink is None:
            raise QgsProcessingException(self.invalidSinkError(parameters, self.OUTPUT_LAYER))

        # Построение графа OSM и установка скоростей
        try:
            importlib.import_module('osmnx')
            import osmnx as ox  # noqa: F401
        except Exception as e:
            raise QgsProcessingException(self.tr(f"OSMnx недоступен: {str(e)}"))

        G, to_wgs, from_wgs = build_graph_for_layers(objects_layer, fire_stations_layer)
        set_graph_travel_times(G, speeds_kmh, kmh_to_mm)

        # Подготовка данных станций
        station_name_field = self._detect_station_name_field(fire_stations_layer)
        fire_stations = list(fire_stations_layer.getFeatures())

        # Обработка каждого объекта
        total_features = objects_layer.featureCount()
        feedback.pushInfo(self.tr(f'Обработка {total_features} объектов...'))

        from osmnx.distance import nearest_nodes
        import networkx as nx

        def sum_route_time_and_length(graph, route_nodes):
            total_time = 0.0
            total_len = 0.0
            for u, v in zip(route_nodes[:-1], route_nodes[1:]):
                data = graph.get_edge_data(u, v)
                if not data:
                    continue
                best_edge = None
                best_time = float('inf')
                for _, ed in data.items():
                    t = ed.get('travel_time')
                    if t is None:
                        continue
                    if t < best_time:
                        best_time = t
                        best_edge = ed
                if best_edge is None:
                    ed = next(iter(data.values()))
                    t = ed.get('travel_time') or 0.0
                    l = ed.get('length') or 0.0
                else:
                    t = best_time
                    l = best_edge.get('length') or 0.0
                total_time += t
                total_len += l
            return total_time, total_len

        for i, obj_feature in enumerate(objects_layer.getFeatures()):
            if feedback.isCanceled():
                break

            # Получение геометрии объекта
            obj_geometry = obj_feature.geometry()
            if obj_geometry.isEmpty():
                continue

            # Определение центра объекта
            if obj_geometry.type() == QgsWkbTypes.PointGeometry:
                obj_point = obj_geometry.asPoint()
            else:
                obj_point = obj_geometry.centroid().asPoint()

            obj_id = obj_feature.id()
            obj_type = QgsWkbTypes.displayString(obj_geometry.wkbType())

            # Поиск узла графа для объекта
            obj_wgs = to_wgs.transform(obj_point.x(), obj_point.y())
            try:
                obj_node = nearest_nodes(G, obj_wgs.x(), obj_wgs.y())
            except Exception:
                continue

            # Функция подсчёта маршрута и времени
            def compute_time_and_route(station_feature):
                st_pt = station_feature.geometry().asPoint()
                st_wgs = to_wgs.transform(st_pt.x(), st_pt.y())
                try:
                    st_node = nearest_nodes(G, st_wgs.x(), st_wgs.y())
                    route_nodes = nx.shortest_path(G, obj_node, st_node, weight='travel_time')
                    t_min, total_len = sum_route_time_and_length(G, route_nodes)
                    return route_nodes, t_min, total_len
                except Exception:
                    return None, float('inf'), float('inf')

            routes_to_write = []  # (route_nodes, t_min, total_len, station)

            if route_type == 0:  # Только ближайшая по времени
                best = (None, float('inf'), float('inf'), None)
                for st in fire_stations:
                    route_nodes, t_min, total_len = compute_time_and_route(st)
                    if t_min < best[1]:
                        best = (route_nodes, t_min, total_len, st)
                if best[0] is not None:
                    routes_to_write.append(best)
            elif route_type == 1:  # Все станции
                for st in fire_stations:
                    route_nodes, t_min, total_len = compute_time_and_route(st)
                    if route_nodes is not None:
                        routes_to_write.append((route_nodes, t_min, total_len, st))
            else:  # В пределах порога времени
                for st in fire_stations:
                    route_nodes, t_min, total_len = compute_time_and_route(st)
                    if route_nodes is not None and t_min <= time_threshold:
                        routes_to_write.append((route_nodes, t_min, total_len, st))

            # Запись маршрутов
            for route_nodes, t_min, total_len, station in routes_to_write:
                try:
                    st_name = station[station_name_field] if station_name_field else f"Station_{station.id()}"
                except Exception:
                    st_name = f"Station_{station.id()}"

                # Геометрия маршрута по узлам графа → CRS проекта
                path_pts = []
                for n in route_nodes:
                    lon = G.nodes[n].get('x')
                    lat = G.nodes[n].get('y')
                    pt_src = from_wgs.transform(lon, lat)
                    path_pts.append(QgsPointXY(pt_src))
                if len(path_pts) < 2:
                    continue
                line_geometry = QgsGeometry.fromPolylineXY(path_pts)

                route_feature = QgsFeature(fields)
                route_feature.setGeometry(line_geometry)
                route_feature['object_id'] = obj_id
                route_feature['station_name'] = st_name
                route_feature['distance_km'] = round(total_len / 1000.0, 2) if total_len != float('inf') else None
                route_feature['response_time_min'] = round(t_min, 2) if t_min != float('inf') else None
                route_feature['object_type'] = obj_type
                route_feature['route_type'] = ['nearest', 'all', 'within_threshold'][route_type]

                sink.addFeature(route_feature)

            # Обновление прогресса
            feedback.setProgress(int(i / total_features * 100))

        return {self.OUTPUT_LAYER: dest_id}

    def _detect_station_name_field(self, layer):
        """Определение подходящего строкового поля с названием подразделения"""
        if layer is None:
            return None
        string_fields = []
        for fld in layer.fields():
            if fld.type() == QVariant.String:
                string_fields.append(fld.name())
        preferred = ['name', 'station', 'station_name', 'Название', 'Наименование']
        lower_map = {f.lower(): f for f in string_fields}
        for key in preferred:
            if key.lower() in lower_map:
                return lower_map[key.lower()]
        return string_fields[0] if string_fields else None

    def find_nearest_station(self, point, stations, distance_calc):
        """Поиск ближайшей пожарной станции"""
        min_distance = float('inf')
        nearest_station = None
        
        for station in stations:
            station_point = station.geometry().asPoint()
            distance = distance_calc.measureLine(point, station_point)
            
            if distance < min_distance:
                min_distance = distance
                nearest_station = station
                
        return nearest_station

    def tr(self, string):
        """Перевод строки"""
        return QCoreApplication.translate('Processing', string)
