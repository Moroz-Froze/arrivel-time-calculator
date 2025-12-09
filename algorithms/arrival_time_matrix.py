"""
Алгоритм расчета матрицы прибытия подразделений пожарной охраны.
"""

__author__    = 'Малютин О.С.'
__date__      = '2025-11-22'
__copyright__ = '(C) 2025 by SPSA'

__revision__  = '$Format:%H$'


import inspect
import os

from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.PyQt.QtGui import QIcon

from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsField,
    QgsProcessingException,
    QgsProcessingAlgorithm,
    QgsProcessing,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterFileDestination,
)

try:
    import osmnx as ox
    import geopandas as gpd
    import pandas as pd
    import networkx as nx
    from shapely.geometry import Point, Polygon, MultiPolygon
    from shapely.ops import unary_union
    from shapely import wkt
    import numpy as np
    ox.settings.log_console = False
    ox.settings.use_cache = True
    OSMNX_AVAILABLE = True
except ImportError:
    OSMNX_AVAILABLE = False

from .genesis.genesis.swiss_knife import DELAY_TIME
from ..graph_tools import get_graph_from_layer


class ATM_Algorithm(QgsProcessingAlgorithm):
    """
    Алгоритм расчета матрицы прибытия подразделений пожарной охраны.

    Результатом является новый векторный слой зданий со столбцами 
    каждому из которых соответствует время прибытия соответствующего 
    подразделения пожарной охраны
    """

    # Параметры входных данных
    ROAD_NETWORK = 'ROAD_NETWORK'
    WEIGHT_FIELD = 'WEIGHT_FIELD'
    FIRE_UNITS = 'FIRE_UNITS'
    UNITS_NAME_FIELD = 'UNITS_NAME_FIELD'
    BUILDINGS = 'BUILDINGS'
    

    
    # Выходные данные
    OUTPUT = 'OUTPUT'

    PRE_GDS_PATH  = '{}.ml'

    def tr(self, string):
        """
        Возвращает перевод для self.tr().
        """
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return ATM_Algorithm()

    def name(self):
        """
        Название алгоритма
        """
        return 'arrival_time_matrix'

    def displayName(self):
        """
        Отображаемое название алгоритма
        """
        return self.tr('Матрица прибытия всех подразделений')

    def group(self):
        """
        Возвращает название группы, к которой принадлежит этот алгоритм.
        """
        return self.tr('Общие алгоритмы')

    def groupId(self):
        """
        Возвращает уникальный идентификатор группы, к которой принадлежит этот алгоритм.
        """
        return 'COMMON'

    def shortHelpString(self):
        """
        Возвращает краткое описание алгоритма
        """
        return self.tr("""
            Алгоритм расчета матрицы прибытия подразделений пожарной охраны.

            Результатом является новый векторный слой зданий со столбцами 
            каждому из которых соответствует время прибытия соответствующего 
            подразделения пожарной охраны

            Параметры:
            - Слой улично-дорожной сети (INPUT): Векторный слой линий дорожной сети
            - Поле времени следования по участкам дорожной сети (EDGES_WEIGHT_FIELD): Поле в слое дорожной сети, содержащее время проезда по участкам
            - Слой пожарных подразделений (FIRE_UNITS): Точечный слой с пожарными подразделениями
            - Слой застройки (BUILDINGS): Полигональный слой с застройкой. Если не указан, будут использованы узлы графа улично-дорожной сети
            
            Выходные данные:
            - Слой застройки с временами прибытия подразделений пожарной охраны
        """)

    def icon(self):
        """
        Возвращает иконку алгоритма
        """
        cmd_folder = os.path.split(inspect.getfile(inspect.currentframe()))[0]
        icon_path  = os.path.join(cmd_folder, '..', 'icons/atm_calc.svg')
        icon_path  = os.path.normpath(icon_path)
        if os.path.exists(icon_path):
            return QIcon(icon_path)
        else:
            return QIcon()

    def initAlgorithm(self, config=None):
        """
        Здесь указываются настройки алгоритма - входы и выходы.
        """

        # Слой улично-дорожной сети
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.ROAD_NETWORK,
            self.tr('Слой улично-дорожной сети'),
            [QgsProcessing.TypeVectorLine],
            defaultValue='Дорожная сеть',
            optional=False
        ))

        # Поле времени следования
        self.addParameter(QgsProcessingParameterField(
           self.WEIGHT_FIELD,
           self.tr('Поле времени следования по участкам дорожной сети'),
           parentLayerParameterName=self.ROAD_NETWORK,
           type=QgsProcessingParameterField.Numeric,
           defaultValue='travel_time',
           optional=False
        ))

        # Слой пожарных подразделений
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.FIRE_UNITS,
            self.tr('Слой пожарных подразделений'),
            [QgsProcessing.TypeVectorPoint],
            defaultValue='Подразделения',
            optional=False
        ))

        # Поле названия подразделения
        self.addParameter(QgsProcessingParameterField(
            self.UNITS_NAME_FIELD,
            self.tr('Поле названия подразделения'),
            parentLayerParameterName=self.FIRE_UNITS,
            type=QgsProcessingParameterField.String,
            defaultValue='name',
            optional=False
        ))

        # Слой застройки
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.BUILDINGS,
            self.tr('Слой застройки'),
            [QgsProcessing.TypeVectorPolygon],
            # defaultValue='Застройка',
            optional=True
        ))

        # Итоговый слой зданий
        self.addParameter(QgsProcessingParameterFileDestination(
                self.OUTPUT, self.tr('Матрица прибытия (Застройка с временами прибытия)'), 'файл Geopackage (*.gpkg)',
            ))



    def processAlgorithm(self, parameters, context, feedback):
        """
        Основная логика алгоритма
        """

        DATA_NODE_FIELD   = 'node'

        
        # Проверяем доступность osmnx
        if not OSMNX_AVAILABLE:
            raise QgsProcessingException(
                self.tr('Необходимо установить библиотеки: osmnx, geopandas, shapely')
            )

        # Получаем входные параметры
        road_network_source  = self.parameterAsVectorLayer(parameters, self.ROAD_NETWORK, context)
        weight_field         = self.parameterAsString(parameters, self.WEIGHT_FIELD, context)
        existed_units_layer  = self.parameterAsSource(parameters, self.FIRE_UNITS, context)
        units_name_field     = self.parameterAsString(parameters, self.UNITS_NAME_FIELD, context)
        target_layer         = self.parameterAsSource(parameters, self.BUILDINGS, context)

        target_file          = self.parameterAsFile(parameters, self.OUTPUT, context)
        
        
        # 1. Подготовка исходных данных
        # ================================================================================================
        feedback.setProgress(5)

        # 1.1. Подготовка графа дорожной сети
        feedback.setProgressText('Формируется граф дорожной сети...')
        pre_gds_file = self.PRE_GDS_PATH.format(road_network_source.id())
        feedback.pushDebugInfo(f'Путь к графу: {pre_gds_file}')
        G = get_graph_from_layer(pre_gds_file, road_network_source, feedback)

        ## Проецируем граф в локальную СК
        G = ox.project_graph(G)

        ## Вывод
        estimated_utm_crs = G.graph['crs']
        feedback.pushDebugInfo(f'Получен граф дорог с количеством узлов - {G.number_of_nodes()} и ребер {G.number_of_edges()}. СК: {estimated_utm_crs}')
        feedback.setProgress(25)


        # 1.2. Подготовка геоданных
        feedback.setProgressText('Подготавливаем данные...')
        if target_layer is None:
            feedback.pushDebugInfo('Слой застройки не указан, поэтому в качестве целей прибытия будут использованы узлы графа')
            target_layer_gdf = ox.graph_to_gdfs(G, edges=False)
            target_layer_gdf = target_layer_gdf.reset_index()
            target_layer_gdf.rename(columns={'osmid': DATA_NODE_FIELD}, inplace=True)
            target_layer_gdf = ox.projection.project_gdf(target_layer_gdf, to_crs=estimated_utm_crs)
        else:
            target_layer_gdf = gpd.GeoDataFrame.from_features(
                list(target_layer.getFeatures()),
                crs = target_layer.sourceCrs().authid()
                )
            # Проецируем в локальную СК и определяем узлы графа, к которым они относятся
            target_layer_gdf                  = ox.projection.project_gdf(target_layer_gdf, to_crs=estimated_utm_crs)
            centroids                         = target_layer_gdf.geometry.centroid
            target_layer_gdf[DATA_NODE_FIELD] = ox.nearest_nodes(G, centroids.x, centroids.y)
            del centroids

        
        # 1.3. Подготовка слоя существующих подразделений
        existed_units_layer_gdf = gpd.GeoDataFrame.from_features(
            list(existed_units_layer.getFeatures()),
            crs = existed_units_layer.sourceCrs().authid()
            )
        existed_units_layer_gdf = ox.projection.project_gdf(existed_units_layer_gdf, to_crs=estimated_utm_crs)
        existed_units_layer_gdf[DATA_NODE_FIELD] = ox.nearest_nodes(G, 
                                                            existed_units_layer_gdf.geometry.x, 
                                                            existed_units_layer_gdf.geometry.y
                                                            )
        # Если поля названия подразделения нет, создаем его
        if not units_name_field in existed_units_layer_gdf.columns:
            existed_units_layer_gdf[units_name_field] = pd.Series([f'#{i}' for i in range(len(existed_units_layer_gdf))])
        
        # Подготавливаем словарь подразделений
        existed_units_dict = dict(zip(existed_units_layer_gdf[DATA_NODE_FIELD], 
                                        existed_units_layer_gdf[units_name_field]))
        feedback.setProgress(35)



        # 2. Расчет требуемой численности пожарных автомобилей
        # ================================================================================================
        feedback.setProgressText('Расчет времен прибытия подразделений пожарной охраны')
        
        # 2.1. Расчет ожидаемого времени прибытия подразделений
        i = 0
        for node, unit_name in existed_units_dict.items():
            times = nx.single_source_dijkstra_path_length(G, node, weight=weight_field)
            times = pd.Series(times, name = unit_name)
            times = times+DELAY_TIME

            # Сопоставляем здания с временем прибытия
            target_layer_gdf = target_layer_gdf.merge(times,
                                                    left_on=DATA_NODE_FIELD, 
                                                    right_index=True,
                                                    how='left')
            feedback.pushDebugInfo(f'Выполнен расчет для {unit_name}')
            feedback.setProgress(40 + int(i * 55))
            i+=1

        # Сбрасываем столбец с кодом узла
        target_layer_gdf = target_layer_gdf.drop(columns=[DATA_NODE_FIELD])


        # 5. Сохраняем результаты
        feedback.setProgressText('Сохраняем изменения...')
        feedback.setProgress(95)

        # Перепроецируем в СК
        if target_layer is not None:
            # исходной застройки
            target_layer_gdf = ox.projection.project_gdf(target_layer_gdf, to_crs=target_layer.sourceCrs().authid())
        else:
            # исходной дороги
            target_layer_gdf = ox.projection.project_gdf(target_layer_gdf, to_crs=road_network_source.sourceCrs().authid())
            
        
        # Сохраняем в итоговый слой
        target_layer_gdf.to_file(target_file)

        # Добавляем полученный слой на карту
        vlayer = QgsVectorLayer(target_file, 'Матрица прибытия', 'ogr')
        QgsProject.instance().addMapLayer(vlayer)
        
        feedback.setProgress(100)
        feedback.setProgressText('OK')
        return {self.OUTPUT: target_file}

