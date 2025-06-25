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
    QgsVectorFileWriter,
    QgsFields,
    QgsField,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsWkbTypes
)
from qgis.PyQt.QtCore import QVariant
import osmnx as ox
import networkx as nx
import geopandas as gpd
from ..utils.speed_management import SpeedManager
from ..utils.osm_utils import load_graph_from_osm
from ..utils.geometry_utils import extract_polygons, calculate_travel_time
from ..utils.layer_management import create_point_layer  # Измененная функция для создания слоя точек

class EndPointsLayerAlgorithm(QgsProcessingAlgorithm):
    """
    Алгоритм для расчёта времени прибытия с использованием дорожной сети из OSM.
    Результатом являются точки в местах конечных объектов с атрибутами времени прибытия.
    """

    INPUT = 'INPUT'
    OUTPUT = 'OUTPUT'
    START_POINTS = 'START_POINTS'
    END_POINTS = 'END_POINTS'
    SPEEDS = 'SPEEDS'
    NETWORK_TYPE = 'NETWORK_TYPE'

    default_speed_limits = SpeedManager.default_speed_limits

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.INPUT,
            self.tr('Границы зоны расчёта'),
            [QgsProcessing.TypeVectorPolygon]
        ))

        self.addParameter(QgsProcessingParameterFileDestination(
            self.OUTPUT,
            self.tr('Output File'),
            'Geopackage file (*.gpkg)',
        ))

        self.addParameter(QgsProcessingParameterFeatureSource(
            self.START_POINTS, 
            self.tr('Пожарные подразделения'), 
            [QgsProcessing.TypeVectorPoint, QgsProcessing.TypeVectorPolygon],
        ))

        self.addParameter(QgsProcessingParameterFeatureSource(
            self.END_POINTS, 
            self.tr('Конечные точки'),
            [QgsProcessing.TypeVectorPoint, QgsProcessing.TypeVectorPolygon],
        ))

        self.addParameter(QgsProcessingParameterEnum(
            self.NETWORK_TYPE,
            self.tr('Тип улично-дорожной сети'),
            [
                self.tr('Вся сеть'),
                self.tr('Только крупные дороги'),
            ],
            defaultValue=0
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
        feedback.pushInfo('Версия библиотек:')
        feedback.pushInfo(f'   osmnx: {ox.__version__}')
        feedback.pushInfo(f'   networkx: {nx.__version__}')

        # Получаем слой границ
        source = self.parameterAsSource(parameters, self.INPUT, context)
        if source is None:
            raise QgsProcessingException(self.invalidSourceError(parameters, self.INPUT))

        # Получаем тип улично-дорожной сети
        network_type_option = self.parameterAsEnum(parameters, self.NETWORK_TYPE, context)
        network_type = 'drive_service' if network_type_option == 0 else 'drive'

        # Загрузка скоростей следования
        speeds = self.parameterAsMatrix(parameters, self.SPEEDS, context)[1::2]
        speed_limits = [float(s) for s in speeds]

        # Извлечение многоугольников и создание графа
        polygons = extract_polygons(source)
        G = load_graph_from_osm(polygons, feedback, network_type)
        if G is None or G.number_of_nodes() == 0:
            feedback.reportError("Граф не загружен или не содержит узлов.")
            return

        # Установка скоростей следования
        speed_manager = SpeedManager()
        speed_manager.set_graph_travel_times(G, speed_limits, morph_function=speed_manager.kmh_to_mm)

        # Получаем стартовые и конечные точки
        start_points_layer = self.parameterAsSource(parameters, self.START_POINTS, context)
        target_points_layer = self.parameterAsSource(parameters, self.END_POINTS, context)

        # Конвертируем в GeoDataFrame
        start_points_gdf = gpd.GeoDataFrame.from_features(list(start_points_layer.getFeatures()), 
                                                         crs=start_points_layer.sourceCrs().authid())
        target_points_gdf = gpd.GeoDataFrame.from_features(list(target_points_layer.getFeatures()), 
                                                          crs=target_points_layer.sourceCrs().authid())

        # Проецируем данные
        start_points_gdf = ox.projection.project_gdf(start_points_gdf)
        target_points_gdf = ox.projection.project_gdf(target_points_gdf)
        G = ox.project_graph(G)

        # Определяем ближайшие узлы для ПСЧ и целевых объектов
        start_points_gdf['node'] = ox.distance.nearest_nodes(G, start_points_gdf.geometry.x, start_points_gdf.geometry.y)
        target_points_gdf['node'] = ox.distance.nearest_nodes(G, target_points_gdf.geometry.x, target_points_gdf.geometry.y)
        
        start_points_nodes = set(start_points_gdf['node'])
        target_points_nodes = set(target_points_gdf['node'])

        # Создаем слой для точек с временем прибытия
        fields = QgsFields()
        fields.append(QgsField("id", QVariant.Int))
        fields.append(QgsField("target_id", QVariant.String))
        fields.append(QgsField("target_name", QVariant.String))
        fields.append(QgsField("station_id", QVariant.String))
        fields.append(QgsField("station_name", QVariant.String))
        fields.append(QgsField("travel_time", QVariant.Double))
        fields.append(QgsField("nearest_node", QVariant.Int))

        output_layer = create_point_layer(fields, target_points_gdf.crs.to_string())

        # Для каждой целевой точки находим минимальное время прибытия
        feature_id = 0
        for target_idx, target_feature in target_points_gdf.iterrows():
            target_node = target_feature['node']
            target_name = target_feature.get('name', str(target_idx))
            target_id = target_feature.get('id', str(target_idx))

            # Рассчитываем все маршруты до этой точки
            routes = nx.shortest_path(G, target=target_node, weight='travel_time')
            
            # Фильтруем только маршруты от пожарных станций
            station_routes = {k: v for k, v in routes.items() if k in start_points_nodes}
            
            if not station_routes:
                feedback.pushWarning(f"Не найдено маршрутов до целевой точки {target_name}")
                continue

            # Для каждой пожарной станции создаем точку с временем прибытия
            for node, route in station_routes.items():
                station_info = start_points_gdf.query(f'node == @node').iloc[0]
                station_name = station_info.get('name', str(node))
                station_id = station_info.get('id', str(node))

                # Рассчитываем время следования
                route_gdf = ox.routing.route_to_gdf(G, route)
                travel_time = sum(route_gdf['travel_time'])

                # Создаем точку в месте целевого объекта
                point = QgsPointXY(target_feature.geometry.x, target_feature.geometry.y)
                feat = QgsFeature(fields)
                feat.setId(feature_id)
                feat.setGeometry(QgsGeometry.fromPointXY(point))
                feat.setAttributes([
                    feature_id,
                    target_id,
                    target_name,
                    station_id,
                    station_name,
                    travel_time,
                    target_node
                ])
                output_layer.dataProvider().addFeature(feat)
                feature_id += 1

                feedback.pushInfo(f'Точка {target_name}: время прибытия от {station_name} = {travel_time:.2f} мин')

        # Сохраняем результаты
        if feature_id == 0:
            feedback.reportError("Не было создано ни одной точки с временем прибытия.")
            return {self.OUTPUT: None}

        output_path = self.parameterAsFileOutput(parameters, self.OUTPUT, context)
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = "arrival_times"
        
        error = QgsVectorFileWriter.writeAsVectorFormatV3(
            output_layer,
            output_path,
            context.transformContext(),
            options
        )
        
        if error[0] != QgsVectorFileWriter.NoError:
            raise QgsProcessingException(f"Ошибка сохранения файла: {error[1]}")
        
        # Добавляем слой на карту
        QgsProject.instance().addMapLayer(output_layer)
        
        return {self.OUTPUT: output_path}


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