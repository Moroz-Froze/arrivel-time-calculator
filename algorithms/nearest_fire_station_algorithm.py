"""
Алгоритм для определения ближайшего пожарного подразделения
"""

from qgis.core import (QgsProcessingAlgorithm, QgsProcessingParameterVectorLayer,
                       QgsProcessingParameterField, QgsProcessingParameterNumber,
                       QgsProcessingParameterFeatureSink, QgsProcessingOutputVectorLayer,
                       QgsFeature, QgsGeometry, QgsPointXY, QgsSpatialIndex,
                       QgsDistanceArea, QgsProject, QgsUnitTypes, QgsProcessingException,
                       QgsField, QgsFields, QgsWkbTypes, QgsRectangle, QgsProcessing)
from qgis.PyQt.QtCore import QCoreApplication, QVariant
from ..graph_utils import (
    build_graph_for_layers,
    set_graph_travel_times,
    kmh_to_mm,
    DEFAULT_SPEEDS_KMH,
)
import os
import importlib
import math


class NearestFireStationAlgorithm(QgsProcessingAlgorithm):
    """
    Алгоритм для определения ближайшего пожарного подразделения
    и расчета времени прибытия для каждого объекта
    """

    # Константы параметров
    OBJECTS_LAYER = 'OBJECTS_LAYER'
    FIRE_STATIONS_LAYER = 'FIRE_STATIONS_LAYER'
    RESPONSE_TIME_FIELD = 'RESPONSE_TIME_FIELD'
    ROAD_SPEEDS_KMH = 'ROAD_SPEEDS_KMH'
    OUTPUT_LAYER = 'OUTPUT_LAYER'

    def tr(self, string):
        """Перевод строки"""
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        """Создание экземпляра алгоритма"""
        return NearestFireStationAlgorithm()

    def name(self):
        """Имя алгоритма"""
        return 'nearest_fire_station'

    def displayName(self):
        """Отображаемое имя алгоритма"""
        return self.tr('Ближайшее пожарное подразделение')

    def group(self):
        """Группа алгоритма"""
        return self.tr('Fire Response Analysis')

    def groupId(self):
        """ID группы алгоритма"""
        return 'fire_response_analysis'

    def shortHelpString(self):
        """Краткая справка"""
        return self.tr(
            "Этот алгоритм определяет ближайшее пожарное подразделение "
            "для каждого объекта и рассчитывает время прибытия."
        )

    def initAlgorithm(self, config=None):
        """Инициализация параметров алгоритма"""
        
        # Входной слой объектов (здания, точечные объекты)
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

        # Поле с названием подразделения выбирается автоматически в процессе

        # Средняя скорость движения (км/ч)
        # Скорости по типам дорог передаются из диалога списком из 5 значений (км/ч)

        # Выходной слой
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT_LAYER,
                self.tr('Выходной слой с временем прибытия')
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

        if objects_layer is None:
            raise QgsProcessingException(self.invalidSourceError(parameters, self.OBJECTS_LAYER))
        
        if fire_stations_layer is None:
            raise QgsProcessingException(self.invalidSourceError(parameters, self.FIRE_STATIONS_LAYER))

        # Создание выходного слоя
        fields = objects_layer.fields()
        fields.append(QgsField('nearest_station', QVariant.String))
        fields.append(QgsField('distance_km', QVariant.Double))
        fields.append(QgsField('response_time_min', QVariant.Double))
        fields.append(QgsField('station_x', QVariant.Double))
        fields.append(QgsField('station_y', QVariant.Double))

        (sink, dest_id) = self.parameterAsSink(
            parameters, self.OUTPUT_LAYER, context,
            fields, objects_layer.wkbType(), objects_layer.sourceCrs()
        )

        if sink is None:
            raise QgsProcessingException(self.invalidSinkError(parameters, self.OUTPUT_LAYER))

        # Построение графа дорог OSM
        try:
            # Проверка наличия osmnx
            importlib.import_module('osmnx')
            import osmnx as ox  # noqa: F401
        except Exception as e:
            raise QgsProcessingException(self.tr(f"OSMnx недоступен: {str(e)}"))

        feedback.pushInfo(self.tr('Построение графа дорог OSM...'))
        G, to_wgs, from_wgs = build_graph_for_layers(objects_layer, fire_stations_layer)
        set_graph_travel_times(G, speeds_kmh, kmh_to_mm)

        # Обработка каждого объекта
        total_features = objects_layer.featureCount()
        feedback.pushInfo(self.tr(f'Обработка {total_features} объектов...'))

        # Вспомогательная функция суммирования времени/длины по маршруту узлов
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

            # Поиск ближайшей станции по кратчайшему времени следования по дорогам
            nearest_station_id = None
            nearest_station_feature = None
            best_time_min = float('inf')
            best_distance_km = float('inf')

            # Узел графа для объекта
            obj_wgs = to_wgs.transform(obj_point.x(), obj_point.y())
            from osmnx.distance import nearest_nodes
            try:
                obj_node = nearest_nodes(G, obj_wgs.x(), obj_wgs.y())
            except Exception:
                continue

            for station_feature in fire_stations_layer.getFeatures():
                station_point = station_feature.geometry().asPoint()
                st_wgs = to_wgs.transform(station_point.x(), station_point.y())
                try:
                    st_node = nearest_nodes(G, st_wgs.x(), st_wgs.y())
                except Exception:
                    continue

                # Кратчайший путь по времени
                import networkx as nx
                try:
                    route = nx.shortest_path(G, obj_node, st_node, weight='travel_time')
                except Exception:
                    continue

                # Суммарное время и длина
                total_time_min, total_len_m = sum_route_time_and_length(G, route)
                total_dist_km = total_len_m / 1000.0 if total_len_m != float('inf') else float('inf')

                if total_time_min < best_time_min:
                    best_time_min = total_time_min
                    best_distance_km = total_dist_km
                    nearest_station_id = station_feature.id()
                    nearest_station_feature = station_feature

            # Расчет времени прибытия
            if nearest_station_feature is not None:
                station_name_field = self._detect_station_name_field(fire_stations_layer)
                station_name = nearest_station_feature[station_name_field] if station_name_field else f"Station_{nearest_station_id}"
                response_time_min = round(best_time_min, 2)
                station_point = nearest_station_feature.geometry().asPoint()
                
                # Создание новой фичи
                new_feature = QgsFeature(fields)
                new_feature.setGeometry(obj_geometry)
                
                # Копирование атрибутов исходного объекта
                for field in objects_layer.fields():
                    new_feature[field.name()] = obj_feature[field.name()]
                
                # Добавление новых атрибутов
                new_feature['nearest_station'] = station_name
                new_feature['distance_km'] = round(best_distance_km, 2)
                new_feature['response_time_min'] = response_time_min
                new_feature['station_x'] = round(station_point.x(), 6)
                new_feature['station_y'] = round(station_point.y(), 6)
                
                sink.addFeature(new_feature)
            else:
                feedback.reportError(self.tr(f'Не найдена ближайшая станция для объекта {obj_feature.id()}'))

            # Обновление прогресса
            feedback.setProgress(int(i / total_features * 100))

        return {self.OUTPUT_LAYER: dest_id}

    def _detect_station_name_field(self, layer):
        """Выбор наиболее подходящего строкового поля для имени станции"""
        if layer is None:
            return None
        string_fields = []
        for fld in layer.fields():
            if fld.type() == QVariant.String:
                string_fields.append(fld.name())
        # Популярные названия полей
        preferred = ['name', 'station', 'station_name', 'Название', 'Наименование']
        lower_map = {f.lower(): f for f in string_fields}
        for key in preferred:
            if key.lower() in lower_map:
                return lower_map[key.lower()]
        return string_fields[0] if string_fields else None