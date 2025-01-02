import osmnx as ox
from shapely.geometry import Polygon

# Переписать! Сделать именно по полигону - сейчас выгружает прямоугольник охватывающий полигоны. Зачем тогда вообще полигон нужен?
def load_graph_from_osm(polygons, feedback):
    feedback.pushInfo("Загрузка графа из OSM...")
    minx, miny, maxx, maxy = polygons.bounds
    polygon = Polygon([(minx, miny), (minx, maxy), (maxx, maxy), (maxx, miny)])
    graph = ox.graph_from_polygon(polygon, network_type='drive_service')
    feedback.pushInfo("Граф успешно загружен.")
    return graph
