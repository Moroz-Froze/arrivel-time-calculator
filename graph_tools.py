'''
Дополнительные функции для работы с графами
'''

import os

try:
    import geopandas as gpd
    GPD_AVAILABLE = True
except ImportError:
    GPD_AVAILABLE = False
    gpd = None

try:
    import osmnx as ox
    OSMNX_AVAILABLE = True
except ImportError:
    OSMNX_AVAILABLE = False
    ox = None

from .algorithms.genesis.graphs.algorithms import graph_rise_from_gpkg

from .algorithms.genesis.graphs.speeds import kmh_to_mm, set_graph_travel_times
from qgis.core import (QgsProcessingException)

def check_file_exists(file_path):
    return os.path.exists(file_path)


def get_graph_from_layer(pre_gds_file,
                         network,
                         feedback,
                         oneway_field_name: str = 'oneway',
                         # lanes_field_name: str = 'lanes',  # Сейчас не реализовано
                         reversed_field_name: str = 'reversed',
                         ):
    """
    Формирует или загружает граф дорожной сети.

    Функция проверяет наличие предварительно сохраненного файла ГДС (GraphML).
    Если файл существует, он загружается. В противном случае создается новый
    граф на основе данных из слоя дорожной сети.

    Параметры:
    ----------
    pre_gds_file : str
        Путь к файлу GraphML с предварительно скомпилированным графом.
    
    network : QgsVectorLayer
        Векторный слой, содержащий данные дорожной сети.
    
    feedback : QgsProcessingFeedback
        Объект обратной связи для отображения прогресса и сообщений.

    Возвращает:
    ----------
    G : networkx.MultiDiGraph
        Граф дорожной сети.

    Исключения:
    -----------
    QgsProcessingException
        Выбрасывается, если в слое дорожной сети отсутствуют необходимые атрибуты.
    """
    if check_file_exists(pre_gds_file):
        # Загружаем граф
        if not OSMNX_AVAILABLE:
            raise QgsProcessingException(
                'Для загрузки предварительно скомпилированного графа необходим osmnx. '
                'Установите osmnx или используйте слой дорог для построения графа.'
            )
        feedback.pushDebugInfo('Используем предварительно скомпилированный ГДС')
        feedback.setProgressText('Загружаем граф дорожной сети')
        G = ox.load_graphml(pre_gds_file)
        roads_gdf = ox.graph_to_gdfs(G, nodes=False)
    else:
        # Формируем граф дорожной сети
        if not GPD_AVAILABLE:
            raise QgsProcessingException(
                'Для построения графа из слоя дорог необходим geopandas. '
                'Установите geopandas: pip install geopandas'
            )
        feedback.setProgressText('Формируем граф дорожной сети')

        # Загружаем данные из слоя дорог
        roads_gdf = gpd.GeoDataFrame.from_features(list(network.getFeatures()), crs=network.sourceCrs().authid())

        # Приводим названия колонок к нижнему регистру
        columns_names_lower = {col: str.lower(col) for col in roads_gdf.columns}
        roads_gdf.rename(columns=columns_names_lower, inplace=True)

        ## Проверяем наличие нужных полей
        if not oneway_field_name in roads_gdf.columns:
            feedback.pushWarning(f'Поле "{oneway_field_name}" отсутствует в списке полей входящего слоя дорожной сети!'
                ' Полученный граф не будет учитывать направления движения по дорогам!'
                                )
        if not reversed_field_name in roads_gdf.columns:
            feedback.pushWarning(f'Поле {reversed_field_name} отсутствует в списке полей входящего слоя дорожной сети!'
                ' Полученный граф может содержать ошибки направления движения техники!'
                                )
        ## Получаем все поля из слоя дорог, за исключением полей 'geometry' и полей ключей
        ## ВАЖНО! Также удаляем поле 'length', так как оно пересчитывается в функции graph_rise_from_gpkg
        key_fields = ['u', 'v', 'key', 'osmid', 'length']
        columns_list = [col for col in roads_gdf.columns if col not in key_fields]
        
        ## Реконструкция графа
        G = graph_rise_from_gpkg(roads_gdf[columns_list],
                                oneway_field_name = oneway_field_name,
                                # lanes_field_name: str = 'lanes',  # Сейчас не реализовано
                                reversed_field_name = reversed_field_name,
                                )
        
    return G