from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (
    QgsProject,
    QgsProcessingException,
    QgsProcessingAlgorithm,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterMatrix,
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

    INPUT = 'INPUT'
    OUTPUT = 'OUTPUT'
    START_POINTS = 'START_POINTS'
    END_POINTS = 'END_POINTS'
    SPEEDS = 'SPEEDS'
    DISPLAY_ROUTES = 'DISPLAY_ROUTES'

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

        # Загрузка скоростей следования
        speed_manager = SpeedManager()
        # speed_limits = speed_manager.load_speed_limits(self.parameterAsMatrix(parameters, self.SPEEDS, context))
        # Временно сделала так - переписать нормально!
        feedback.pushWarning('Скорости прописаны в коде!')
        speed_limits = [49, 37, 26, 16, 5]


        # Извлечение многоугольников и создание графа
        polygons = extract_polygons(source)
        G = load_graph_from_osm(polygons, feedback)
        if G is None or G.number_of_nodes() == 0:
            feedback.reportError("Граф не загружен или не содержит узлов.")
            return
        # Установка скоростей следования времен следования для ребер графа
        speed_manager.set_graph_travel_times(G, speed_limits, morph_function=speed_manager.kmh_to_mm)

        # Получаем стартовые и конечные точки
        # Загрузка слоя стартовых точек
        # start_points_layer  = self.parameterAsVectorLayer(parameters, self.START_POINTS, context)
        start_points_layer  = self.parameterAsSource(parameters, self.START_POINTS, context)
        # Загрузка слоя конечных точек
        # target_points_layer = self.parameterAsVectorLayer(parameters, self.END_POINTS, context)
        target_points_layer = self.parameterAsSource(parameters, self.END_POINTS, context)

        # Это не имеет смысла - параметры обязательные:
        # if not start_points_layer:
        #     feedback.reportError("Начальные точки не указаны.")
        #     return
        # if not start_points_layer:
        #     feedback.reportError("Начальные точки не указаны.")
        #     return

        # Получаем датасеты стартовых и конечных точек
        start_points_gdf = gpd.GeoDataFrame.from_features(list(start_points_layer.getFeatures()), crs=start_points_layer.sourceCrs().authid())
        target_points_gdf = gpd.GeoDataFrame.from_features(list(target_points_layer.getFeatures()), crs=target_points_layer.sourceCrs().authid())

        # Нужно очень внимательно проверять, чтобы все слои были  единой СК
        # Перепроецируем полученные датасеты в местную СК
        start_points_gdf = ox.project_gdf(start_points_gdf)
        target_points_gdf = ox.project_gdf(target_points_gdf)

        # Перепроецируем граф в местную СК
        GU = G.copy()   # Неспроецированный граф
        G = ox.project_graph(G)



        # Создаем слой маршрутов (если отображение включено)
        layer = None
        if display_routes:
            layer = create_route_layer()

        # Расчёт маршрутов
        total_routes = len(start_points_gdf) * len(target_points_gdf)
        route_count = 0

        # Перебор всех точек - это неудачное решение
        # т.к. цикл по всем точкам может занять много времени
        # Лучше использовать функции из networkx, которые рассчитывают сразу
        # множество маршрутов
        for sp_id, start_feature in start_points_gdf.iterrows():
            start_x, start_y = start_feature.geometry.x, start_feature.geometry.y
            start_name = start_feature['name'] if 'name' in start_points_gdf.columns else str(sp_id)

            for ep_id, end_feature in target_points_gdf.iterrows():
                
                # Останавливает выполнение алгоритма, если нажата кнопка Cancel
                if feedback.isCanceled():
                    break

                end_x, end_y = end_feature.geometry.x, end_feature.geometry.y
                end_name = end_feature['name'] if 'name' in target_points_gdf.columns else str(ep_id)

                try:
                    start_node = ox.distance.nearest_nodes(G, start_x, start_y)
                    end_node = ox.distance.nearest_nodes(G, end_x, end_y)
                    # Это не правильно - кратчайший путь не есть быстрейший!!!
                    # ПЕРЕПИСАТЬ!!! Вместо 'length' использовать 'travel_time' устанавливаемую `set_graph_travel_times`
                    #  и другую функцию Дейкстры из networkx
                    # Там есть функции которые сразу рассчитывают и маршрут и время.
                    # Читай документацию networkx!
                    # route = nx.shortest_path(G, start_node, end_node, weight='length')
                    # travel_time = calculate_travel_time(G, route, speed_limits)
                    route = nx.shortest_path(G, start_node, end_node, weight='travel_time')
                    travel_time = sum(ox.routing.route_to_gdf(G, route, weight='travel_time')['travel_time'])

                    feedback.pushInfo(f'Маршрут: {start_name} → {end_name}, Время: {travel_time:.2f} минут')

                    # Добавление маршрута в слой, если отображение включено
                    if display_routes:
                        display_route(layer, route, travel_time, start_name, end_name, GU)

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