"""
Алгоритм для создания слоя времени прибытия всех подразделений с учетом рангов пожара
"""

from qgis.core import (QgsProcessingAlgorithm, QgsProcessingParameterVectorLayer,
                       QgsProcessingParameterField, QgsProcessingParameterNumber,
                       QgsProcessingParameterFeatureSink, QgsProcessingParameterEnum,
                       QgsProcessingParameterString, QgsFeature, QgsGeometry, 
                       QgsPointXY, QgsDistanceArea, QgsProject, QgsUnitTypes, 
                       QgsProcessingException, QgsField, QgsFields, QgsWkbTypes, QgsProcessing)
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


class AllStationsResponseAlgorithm(QgsProcessingAlgorithm):
    """
    Алгоритм для создания слоя времени прибытия всех подразделений
    с учетом различных рангов пожара и количества выезжающих подразделений
    """

    # Константы параметров
    OBJECTS_LAYER = 'OBJECTS_LAYER'
    FIRE_STATIONS_LAYER = 'FIRE_STATIONS_LAYER'
    STATION_NAME_FIELD = 'STATION_NAME_FIELD'  # больше не параметр, используется для ключа выхода
    ROAD_SPEEDS_KMH = 'ROAD_SPEEDS_KMH'
    FIRE_RANK = 'FIRE_RANK'
    MAX_STATIONS = 'MAX_STATIONS'
    OUTPUT_LAYER = 'OUTPUT_LAYER'

    def tr(self, string):
        """Перевод строки"""
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        """Создание экземпляра алгоритма"""
        return AllStationsResponseAlgorithm()

    def name(self):
        """Имя алгоритма"""
        return 'all_stations_response'

    def displayName(self):
        """Отображаемое имя алгоритма"""
        return self.tr('Анализ времени прибытия всех подразделений')

    def icon(self):
        """Иконка алгоритма для панели инструментов Processing"""
        plugin_root = os.path.dirname(os.path.dirname(__file__))
        return QIcon(os.path.join(plugin_root, 'icons', 'all_stations_response_algorithm_icon.png'))

    def group(self):
        """Группа алгоритма"""
        return self.tr('Fire Response Analysis')

    def groupId(self):
        """ID группы алгоритма"""
        return 'fire_response_analysis'

    def shortHelpString(self):
        """Краткая справка"""
        return self.tr(
            "Этот алгоритм создает слой с анализом времени прибытия всех подразделений "
            "с учетом различных рангов пожара и количества выезжающих подразделений."
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

        # Название подразделения определяется автоматически при выполнении

        # Тип подразделения не используется

        # Средняя скорость движения (км/ч)
        # Скорости по типам дорог приходят списком из 5 значений (км/ч) из диалога

        # Ранг пожара
        self.addParameter(
            QgsProcessingParameterEnum(
                self.FIRE_RANK,
                self.tr('Ранг пожара'),
                options=[self.tr('1-й ранг (1-2 подразделения)'),
                        self.tr('2-й ранг (3-4 подразделения)'),
                        self.tr('3-й ранг (5-6 подразделений)'),
                        self.tr('4-й ранг (7-8 подразделений)'),
                        self.tr('5-й ранг (9+ подразделений)')],
                defaultValue=1
            )
        )

        # Максимальное количество подразделений
        self.addParameter(
            QgsProcessingParameterNumber(
                self.MAX_STATIONS,
                self.tr('Максимальное количество подразделений'),
                type=QgsProcessingParameterNumber.Integer,
                minValue=1,
                maxValue=20,
                defaultValue=6
            )
        )

        # Выходной слой
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT_LAYER,
                self.tr('Выходной слой анализа подразделений')
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        """Основная логика обработки"""
        
        # Получение параметров
        objects_layer = self.parameterAsVectorLayer(parameters, self.OBJECTS_LAYER, context)
        fire_stations_layer = self.parameterAsVectorLayer(parameters, self.FIRE_STATIONS_LAYER, context)
        station_name_field = self._detect_station_name_field(fire_stations_layer)
        speeds_kmh = parameters.get(self.ROAD_SPEEDS_KMH, DEFAULT_SPEEDS_KMH)
        if not isinstance(speeds_kmh, list) or len(speeds_kmh) != 5:
            speeds_kmh = DEFAULT_SPEEDS_KMH
        fire_rank = self.parameterAsInt(parameters, self.FIRE_RANK, context)
        max_stations = self.parameterAsInt(parameters, self.MAX_STATIONS, context)

        if objects_layer is None:
            raise QgsProcessingException(self.invalidSourceError(parameters, self.OBJECTS_LAYER))
        
        if fire_stations_layer is None:
            raise QgsProcessingException(self.invalidSourceError(parameters, self.FIRE_STATIONS_LAYER))

        # Определение количества подразделений по рангу
        stations_by_rank = {
            0: min(2, max_stations),    # 1-й ранг
            1: min(4, max_stations),    # 2-й ранг
            2: min(6, max_stations),    # 3-й ранг
            3: min(8, max_stations),    # 4-й ранг
            4: max_stations             # 5-й ранг
        }
        
        required_stations = stations_by_rank[fire_rank]

        # Создание полей выходного слоя
        fields = QgsFields()
        fields.append(QgsField('object_id', QVariant.Int))
        fields.append(QgsField('fire_rank', QVariant.Int))
        fields.append(QgsField('total_stations', QVariant.Int))
        fields.append(QgsField('first_arrival_min', QVariant.Double))
        fields.append(QgsField('last_arrival_min', QVariant.Double))
        fields.append(QgsField('avg_arrival_min', QVariant.Double))
        fields.append(QgsField('station_list', QVariant.String))
        fields.append(QgsField('response_coverage', QVariant.String))

        (sink, dest_id) = self.parameterAsSink(
            parameters, self.OUTPUT_LAYER, context,
            fields, objects_layer.wkbType(), objects_layer.sourceCrs()
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

            # Узел графа для объекта
            obj_wgs = to_wgs.transform(obj_point.x(), obj_point.y())
            try:
                obj_node = nearest_nodes(G, obj_wgs.x(), obj_wgs.y())
            except Exception:
                continue

            # Подсчёт времени до всех станций по сети
            station_distances = []
            for station in fire_stations:
                st_pt = station.geometry().asPoint()
                st_wgs = to_wgs.transform(st_pt.x(), st_pt.y())
                try:
                    st_node = nearest_nodes(G, st_wgs.x(), st_wgs.y())
                    route_nodes = nx.shortest_path(G, obj_node, st_node, weight='travel_time')
                    t_min, total_len = sum_route_time_and_length(G, route_nodes)
                    dist_km = total_len / 1000.0
                except Exception:
                    t_min = float('inf')
                    dist_km = float('inf')

                station_name = station[station_name_field] if station_name_field else f"Station_{station.id()}"

                station_distances.append({
                    'station': station,
                    'distance_km': dist_km,
                    'response_time_min': t_min,
                    'name': station_name
                })

            # Сортировка по времени прибытия
            station_distances.sort(key=lambda x: x['response_time_min'])

            # Выбор необходимого количества станций
            selected_stations = station_distances[:required_stations]
            
            if len(selected_stations) == 0:
                continue

            # Расчет статистики
            response_times = [s['response_time_min'] for s in selected_stations]
            first_arrival = min(response_times)
            last_arrival = max(response_times)
            avg_arrival = sum(response_times) / len(response_times)
            
            # Создание списка станций
            station_list = "; ".join([f"{s['name']} ({s['response_time_min']:.1f}мин)" for s in selected_stations])
            
            # Определение покрытия
            if first_arrival <= 5:
                coverage = "Отличное"
            elif first_arrival <= 10:
                coverage = "Хорошее"
            elif first_arrival <= 20:
                coverage = "Удовлетворительное"
            else:
                coverage = "Неудовлетворительное"

            # Создание новой фичи
            new_feature = QgsFeature(fields)
            new_feature.setGeometry(obj_geometry)
            new_feature['object_id'] = obj_id
            new_feature['fire_rank'] = fire_rank + 1
            new_feature['total_stations'] = len(selected_stations)
            new_feature['first_arrival_min'] = round(first_arrival, 1)
            new_feature['last_arrival_min'] = round(last_arrival, 1)
            new_feature['avg_arrival_min'] = round(avg_arrival, 1)
            new_feature['station_list'] = station_list
            new_feature['response_coverage'] = coverage
            
            sink.addFeature(new_feature)

            # Обновление прогресса
            feedback.setProgress(int(i / total_features * 100))

        return {self.OUTPUT_LAYER: dest_id}

    def _detect_station_name_field(self, layer):
        """Определение строкового поля имени подразделения"""
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

    def tr(self, string):
        """Перевод строки"""
        return QCoreApplication.translate('Processing', string)
