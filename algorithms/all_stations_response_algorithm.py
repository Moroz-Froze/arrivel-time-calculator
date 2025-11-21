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
    find_nearest_node,
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
    USE_CACHE = 'USE_CACHE'
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
            "с учетом всех рангов пожара одновременно. Рассчитываются все ранги: "
            "1 ранг (1 подразделение), 1-бис (2 подразделения), 2 ранг (3 подразделения), "
            "3 ранг (4 подразделения), 4 ранг (5 подразделений), 5 ранг (6 подразделений)."
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

        # Использование кеша графа
        self.addParameter(
            QgsProcessingParameterEnum(
                self.USE_CACHE,
                self.tr('Использовать кеширование графа'),
                options=[self.tr('Да'), self.tr('Нет')],
                defaultValue=0
            )
        )

        # Примечание: Алгоритм рассчитывает все ранги пожара одновременно

        # Выходной слой
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT_LAYER,
                self.tr('Выходной слой анализа подразделений')
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        """Основная логика обработки с использованием матрицы времени прибытия для всех рангов"""
        
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

        # Определение количества подразделений по рангу (согласно требованиям пользователя)
        fire_ranks = {
            "1 ранг": 1,      # 1 подразделение
            "1-бис": 2,       # 2 подразделения
            "2 ранг": 3,      # 3 подразделения
            "3 ранг": 4,      # 4 подразделения
            "4 ранг": 5,      # 5 подразделений
            "5 ранг": 6       # 6 подразделений
        }

        # Создание полей выходного слоя для всех рангов
        fields = QgsFields()
        fields.append(QgsField('object_id', QVariant.Int))
        
        # Добавляем поля для каждого ранга
        for rank_name in fire_ranks.keys():
            fields.append(QgsField(f'{rank_name}_min', QVariant.Double))  # Минимальное время прибытия
            fields.append(QgsField(f'{rank_name}_max', QVariant.Double))  # Максимальное время прибытия
            fields.append(QgsField(f'{rank_name}_avg', QVariant.Double))  # Среднее время прибытия
        
        # Общие поля
        fields.append(QgsField('arrival_time_mean', QVariant.Double))  # Среднее по всем рангам
        fields.append(QgsField('arrival_time_max', QVariant.Double))  # Максимальное по всем рангам
        fields.append(QgsField('arrival_time_min', QVariant.Double))  # Минимальное по всем рангам
        fields.append(QgsField('evaluation', QVariant.String))  # Оценка по среднему времени прибытия

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

        # Получение параметра кеширования
        use_cache = self.parameterAsInt(parameters, self.USE_CACHE, context) == 0
        
        feedback.pushInfo(self.tr('Построение графа дорог OSM...'))
        
        G, to_wgs, from_wgs = build_graph_for_layers(
            objects_layer, 
            fire_stations_layer,
            use_cache=use_cache
        )
        set_graph_travel_times(G, speeds_kmh, kmh_to_mm)

        station_name_field = self._detect_station_name_field(fire_stations_layer)
        fire_stations = list(fire_stations_layer.getFeatures())

        import networkx as nx

        # Шаг 1: Нахождение узлов графа для всех пожарных станций
        feedback.pushInfo(self.tr('Определение узлов графа для пожарных подразделений...'))
        station_nodes = {}
        
        for station in fire_stations:
            st_pt = station.geometry().asPoint()
            st_wgs = to_wgs.transform(st_pt.x(), st_pt.y())
            try:
                st_node = find_nearest_node(G, st_wgs.x(), st_wgs.y())
                if st_node is None:
                    feedback.reportError(self.tr(f'Не удалось найти узел для станции {station.id()}: узел не найден'))
                    continue
                station_name = station[station_name_field] if station_name_field else f"Station_{station.id()}"
                station_nodes[station_name] = st_node
            except Exception as e:
                feedback.reportError(self.tr(f'Не удалось найти узел для станции {station.id()}: {str(e)}'))
                continue

        if len(station_nodes) == 0:
            raise QgsProcessingException(self.tr('Не удалось найти узлы графа ни для одной станции'))

        # Шаг 2: Подготовка данных объектов и нахождение их узлов
        feedback.pushInfo(self.tr('Подготовка данных объектов...'))
        objects_data = []
        objects_nodes_set = set()
        
        for obj_feature in objects_layer.getFeatures():
            obj_geometry = obj_feature.geometry()
            if obj_geometry.isEmpty():
                continue

            # Определение центра объекта
            if obj_geometry.type() == QgsWkbTypes.PointGeometry:
                obj_point = obj_geometry.asPoint()
            else:
                obj_point = obj_geometry.centroid().asPoint()

            obj_id = obj_feature.id()
            obj_wgs = to_wgs.transform(obj_point.x(), obj_point.y())
            
            try:
                obj_node = find_nearest_node(G, obj_wgs.x(), obj_wgs.y())
                if obj_node is not None:
                    objects_data.append({
                        'feature': obj_feature,
                        'geometry': obj_geometry,
                        'id': obj_id,
                        'node': obj_node
                    })
                    objects_nodes_set.add(obj_node)
            except Exception:
                continue

        total_features = len(objects_data)
        if total_features == 0:
            raise QgsProcessingException(self.tr('Не найдено объектов для обработки'))

        feedback.pushInfo(self.tr(f'Найдено {total_features} объектов и {len(station_nodes)} подразделений'))

        # Шаг 3: Вычисление матрицы времени прибытия
        feedback.pushInfo(self.tr('Вычисление матрицы времени прибытия...'))
        arrival_times_matrix = {}  # {station_name: {node: time}}
        
        total_stations = len(station_nodes)
        for idx, (station_name, station_node) in enumerate(station_nodes.items()):
            if feedback.isCanceled():
                break
                
            progress_pct = round(100 * idx / total_stations, 1)
            feedback.pushInfo(self.tr(f'{progress_pct}% : {station_name}...'))
            
            try:
                # Вычисление кратчайших путей от станции ко всем узлам объектов
                arrival_times = nx.shortest_path_length(
                    G,
                    source=station_node,
                    weight='travel_time'
                )
                # Фильтруем только узлы объектов
                arrival_times_filtered = {
                    k: v for k, v in arrival_times.items() 
                    if k in objects_nodes_set
                }
                arrival_times_matrix[station_name] = arrival_times_filtered
                feedback.pushInfo(self.tr(f'{progress_pct}% : {station_name}... OK'))
            except Exception as e:
                feedback.reportError(self.tr(f'Ошибка при расчете для {station_name}: {str(e)}'))
                arrival_times_matrix[station_name] = {}

        # Шаг 4: Обработка объектов с использованием матрицы для всех рангов
        feedback.pushInfo(self.tr('Обработка объектов с использованием матрицы времени прибытия для всех рангов...'))
        
        for i, obj_data in enumerate(objects_data):
            if feedback.isCanceled():
                break

            obj_feature = obj_data['feature']
            obj_geometry = obj_data['geometry']
            obj_id = obj_data['id']
            obj_node = obj_data['node']

            # Получение времен прибытия для данного узла из всех станций
            station_times = []
            for station_name in station_nodes.keys():
                if obj_node in arrival_times_matrix.get(station_name, {}):
                    time_min = arrival_times_matrix[station_name][obj_node]
                    station_times.append({
                        'name': station_name,
                        'response_time_min': time_min
                    })

            if len(station_times) == 0:
                continue

            # Сортировка по времени прибытия
            station_times.sort(key=lambda x: x['response_time_min'])
            
            # Получаем все времена прибытия для расчетов
            all_times = [s['response_time_min'] for s in station_times]

            # Расчет статистики для каждого ранга
            rank_results = {}
            for rank_name, units_count in fire_ranks.items():
                if len(station_times) < units_count:
                    # Если доступных станций меньше, чем требуется для ранга
                    selected_times = all_times
                else:
                    selected_times = all_times[:units_count]
                
                if len(selected_times) > 0:
                    rank_results[rank_name] = {
                        'min': min(selected_times),
                        'max': max(selected_times),
                        'avg': sum(selected_times) / len(selected_times)
                    }
                else:
                    rank_results[rank_name] = {
                        'min': float('inf'),
                        'max': float('inf'),
                        'avg': float('inf')
                    }

            # Расчет общих статистик (по минимальному времени из всех рангов)
            all_min_times = [r['min'] for r in rank_results.values() if r['min'] != float('inf')]
            all_max_times = [r['max'] for r in rank_results.values() if r['max'] != float('inf')]
            all_avg_times = [r['avg'] for r in rank_results.values() if r['avg'] != float('inf')]
            
            arrival_time_min = min(all_min_times) if all_min_times else float('inf')
            arrival_time_max = max(all_max_times) if all_max_times else float('inf')
            arrival_time_mean = sum(all_avg_times) / len(all_avg_times) if all_avg_times else float('inf')

            # Создание новой фичи
            new_feature = QgsFeature(fields)
            new_feature.setGeometry(obj_geometry)
            new_feature['object_id'] = obj_id
            
            # Заполнение полей для каждого ранга
            for rank_name in fire_ranks.keys():
                rank_data = rank_results[rank_name]
                new_feature[f'{rank_name}_min'] = round(rank_data['min'], 1) if rank_data['min'] != float('inf') else None
                new_feature[f'{rank_name}_max'] = round(rank_data['max'], 1) if rank_data['max'] != float('inf') else None
                new_feature[f'{rank_name}_avg'] = round(rank_data['avg'], 1) if rank_data['avg'] != float('inf') else None
            
            # Общие поля
            new_feature['arrival_time_min'] = round(arrival_time_min, 1) if arrival_time_min != float('inf') else None
            new_feature['arrival_time_max'] = round(arrival_time_max, 1) if arrival_time_max != float('inf') else None
            new_feature['arrival_time_mean'] = round(arrival_time_mean, 1) if arrival_time_mean != float('inf') else None
            
            # Оценка по среднему времени прибытия (сравнение с 10 минутами)
            if arrival_time_mean != float('inf') and arrival_time_mean is not None:
                if arrival_time_mean <= 10:
                    evaluation = "удовлетворительно"
                else:
                    evaluation = "не удовлетворительно"
            else:
                evaluation = None
            
            new_feature['evaluation'] = evaluation
            
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
