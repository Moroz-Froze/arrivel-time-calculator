import osmnx as ox
from shapely.geometry import Polygon

# Переписать! Сделать именно по полигону - сейчас выгружает прямоугольник охватывающий полигоны. Зачем тогда вообще полигон нужен?
def load_graph_from_osm(polygons, feedback, network_type='drive_service'):
    '''
    Загрузка графа дорожной сети из OSM

    # Аргументы
    `polygons` - список полигонов, которые нужно загрузить

    `feedback` - объект для вывода сообщений

    `network_type` - тип дорог, которые нужно загрузить:
        * `"drive"` - только крупные дороги
        * `"drive_service"` - все дороги

    '''
    feedback.pushInfo("Загрузка графа из OSM...")
    minx, miny, maxx, maxy = polygons.bounds
    polygon = Polygon([(minx, miny), (minx, maxy), (maxx, maxy), (maxx, miny)])
    graph = ox.graph_from_polygon(polygon, network_type = network_type)
    feedback.pushInfo("Граф успешно загружен.")
    return graph
