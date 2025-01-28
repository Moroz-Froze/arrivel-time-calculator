from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (
    QgsProject,
    QgsProcessingException,
    QgsProcessingAlgorithm,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterMatrix,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFileDestination,
    QgsProcessing,
    QgsProcessingParameterBoolean
)
import osmnx as ox
import networkx as nx
import geopandas as gpd
from ..utils.speed_management import SpeedManager
from ..utils.osm_utils import load_graph_from_osm
from ..utils.geometry_utils import extract_polygons, calculate_travel_time  # Импорт функций работы с геометрией
from ..utils.layer_management import create_route_layer, display_route  # Импорт функций для работы с графическими слоями


class ArrivalTimeCalculatorAlgorithm(QgsProcessingAlgorithm):
    """
    Алгоритм для расчёта времени прибытия с использованием дорожной сети из OSM.
    """

    INPUT          = 'INPUT'
    OUTPUT         = 'OUTPUT'
    START_POINTS   = 'START_POINTS'
    END_POINTS     = 'END_POINTS'
    SPEEDS         = 'SPEEDS'
    DISPLAY_ROUTES = 'DISPLAY_ROUTES'
    NETWORK_TYPE   = 'NETWORK_TYPE'

    default_speed_limits = SpeedManager.default_speed_limits  # Используем по умолчанию скорости из SpeedManager

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.INPUT,
            self.tr('Границы зоны расчёта'),
            [QgsProcessing.TypeVectorPolygon]
        ))

        # self.addParameter(QgsProcessingParameterBoolean(
        #     self.DISPLAY_ROUTES,
        #     self.tr('Отображение маршрута'),
        #     defaultValue=True  # По умолчанию маршруты отображаются
        # ))

        self.addParameter(QgsProcessingParameterFileDestination(
            self.OUTPUT,
            self.tr('Output File'),
            'Geopackage file (*.gpkg)',
        ))

        self.addParameter(QgsProcessingParameterFeatureSource(
            self.START_POINTS, self.tr('Пожарные подразделения'), [QgsProcessing.TypeVectorPoint, QgsProcessing.TypeVectorPolygon],
        ))

        self.addParameter(QgsProcessingParameterFeatureSource(
            self.END_POINTS, self.tr('Конечные точки'),
            [QgsProcessing.TypeVectorPoint, QgsProcessing.TypeVectorPolygon],       # В коде нужно предусмотреть, чтобы расчет проводился и для точек и полигонов - сейчас только для точек 
            # optional=True, # Пусть будет обязательным - для расчета узлов графа мы отдельный алгоритм лучше сделаем.
        ))

        # Целевая метрика для оптимизации
        self.addParameter(QgsProcessingParameterEnum(
            self.NETWORK_TYPE,
            self.tr('Тип улично-дорожной сети'),
            [
                self.tr('Вся сеть'),
                self.tr('Только крупные дороги'),
            ],
            defaultValue=0
            ))
        
        # Скорости следования
        self.addParameter(
            QgsProcessingParameterMatrix(
                self.SPEEDS,
                self.tr('Скорости следования'),
                numberRows=5,
                hasFixedNumberRows=True,
                headers=[self.tr('Тип дороги'), self.tr('Скорость, км/ч')],
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
        # display_routes = self.parameterAsBoolean(parameters, self.DISPLAY_ROUTES, context)
        display_routes = True

        feedback.pushInfo('Версия библиотек:')
        feedback.pushInfo(f'   osmnx: {ox.__version__}')
        feedback.pushInfo(f'   networkx: {nx.__version__}')

        # Получаем слой границ и проверяем его
        source = self.parameterAsSource(parameters, self.INPUT, context)
        if source is None:
            raise QgsProcessingException(self.invalidSourceError(parameters, self.INPUT))

        # Получаем тип улично-дорожной сети
        network_type_option    = self.parameterAsEnum(parameters, self.NETWORK_TYPE, context)
        if network_type_option == 0:
            feedback.pushInfo('Загрузка всей улично-дорожной сети')
            network_type = 'drive_service'
        else:
            feedback.pushInfo('Загрузка только крупных дорог')
            network_type = 'drive'


        # Загрузка скоростей следования
        speed_manager = SpeedManager()
        # speed_limits = speed_manager.load_speed_limits(self.parameterAsMatrix(parameters, self.SPEEDS, context))
        # Временно сделал так - переписать нормально!
        # feedback.pushWarning('Скорости прописаны в коде!')
        # speed_limits = [49, 37, 26, 16, 5]
        speeds            = self.parameterAsMatrix(parameters, self.SPEEDS, context)[1::2]
        speed_limits      = [float(s) for s in speeds]
        # feedback.pushWarning(str(speed_limits))


        # Извлечение многоугольников и создание графа
        polygons = extract_polygons(source)
        G = load_graph_from_osm(polygons, feedback, network_type)
        if G is None or G.number_of_nodes() == 0:
            feedback.reportError("Граф не загружен или не содержит узлов.")
            return

        # Установка скоростей следования времен следования для ребер графа
        speed_manager.set_graph_travel_times(G, speed_limits, morph_function=speed_manager.kmh_to_mm)

        # Получаем стартовые и конечные точки
        # Загрузка слоя стартовых точек
        start_points_layer  = self.parameterAsSource(parameters, self.START_POINTS, context)
        # Загрузка слоя конечных точек
        target_points_layer = self.parameterAsSource(parameters, self.END_POINTS, context)

        # Получаем датасеты стартовых и конечных точек
        start_points_gdf = gpd.GeoDataFrame.from_features(list(start_points_layer.getFeatures()), crs=start_points_layer.sourceCrs().authid())
        target_points_gdf = gpd.GeoDataFrame.from_features(list(target_points_layer.getFeatures()), crs=target_points_layer.sourceCrs().authid())

        # Нужно очень внимательно проверять, чтобы все слои были  единой СК
        # Перепроецируем полученные датасеты в местную СК
        start_points_gdf = ox.projection.project_gdf(start_points_gdf)
        target_points_gdf = ox.projection.project_gdf(target_points_gdf)

        # Перепроецируем граф в местную СК
        GU = G.copy()   # Сохраняем неспроецированный граф для отрисовки маршрутов - потом переписать!
        G = ox.project_graph(G)



        # Создаем слой маршрутов (если отображение включено)
        layer = None
        if display_routes:
            layer = create_route_layer()

        # Расчёт маршрутов
        total_routes = len(start_points_gdf) * len(target_points_gdf)
        route_count = 0

        # Определяем ближайшие узлы ПСЧ
        nearest_nodes = ox.distance.nearest_nodes(G, start_points_gdf.geometry.x, start_points_gdf.geometry.y)
        start_points_gdf['node'] = nearest_nodes
        start_points_nodes = set(start_points_gdf['node'])

        # Определяем ближайшие узлы для целевых объектов
        nearest_nodes = ox.distance.nearest_nodes(G, target_points_gdf.geometry.x, target_points_gdf.geometry.y)
        target_points_gdf['node'] = nearest_nodes

        # Рассчитываем сразу все маршруты для каждой из целей
        feedback.pushInfo('='*40)
        for ep_id, end_feature in target_points_gdf.iterrows():
            end_name = end_feature['name'] if 'name' in target_points_gdf.columns else str(ep_id)

            # Расчет маршрутов
            routes = nx.shortest_path(G,
                              target    = end_feature['node'],
                              weight    = 'travel_time')
            routes = {k:v for k,v in routes.items() if k in start_points_nodes}

            # Перебор маршрутов
            for node, route in routes.items():
                start_points_gdf_cur = start_points_gdf.query(f'node == @node').iloc[0]
                start_name = start_points_gdf_cur['name'] if 'name' in start_points_gdf.columns else str(node)

                # Выбор маршрута
                route_gdf = ox.routing.route_to_gdf(G, route)  #, weight='time')

                # Расчет времени следования по данному маршруту
                travel_time = sum(route_gdf['travel_time'])

                # Печать результата расчета
                feedback.pushInfo(f'Маршрут: {start_name} → {end_name}, Время: {travel_time:.2f} минут')

                # Добавление маршрута в слой, если отображение включено
                if display_routes:
                    display_route(layer, route, travel_time, start_name, end_name, GU)

                # Печать состояния
                route_count += 1
                feedback.setProgress(int((route_count / total_routes) * 100))
            
            # Окончание расчета для объекта
            feedback.pushInfo('='*40)

        # Добавляем слой с маршрутами на карту (если отображение включено)
        if display_routes and route_count > 0:
            layer.updateExtents()
            QgsProject.instance().addMapLayer(layer)
            # !!! Не создает постоянный слой! Так не должно быть !!!
            return {self.OUTPUT: parameters[self.OUTPUT]}
            # return {self.OUTPUT: layer}
        
        if route_count == 0:
            feedback.reportError("Маршруты не были рассчитаны.")

        return {self.OUTPUT: parameters[self.OUTPUT]}

    def name(self):
        return 'fire_truck_arrival_time_calculator'

    def displayName(self):
        return "Оценка времени прибытия"

    def group(self):
        return "Оценка реагирования сил и средств пожарной охраны"

    def groupId(self):
        return 'fire_response'

    def createInstance(self):
        return ArrivalTimeCalculatorAlgorithm()

    def shortHelpString(self):
        return self.tr(
            '''
            Рассчитывает время прибытия пожарных подразделений к указанным целевым точкам (или узлам графа)
            '''
        )