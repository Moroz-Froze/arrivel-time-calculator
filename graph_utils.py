"""
Утилиты для построения графа дорог OSM и расчёта времени следования
с учётом типов дорог и скоростей для пожарной техники.
"""

from typing import List, Tuple, Optional
import os
import hashlib
import pickle
import warnings

try:
    import osmnx as ox
    import networkx as nx
except Exception as e:  # pragma: no cover
    ox = None
    nx = None

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProject,
    QgsRectangle,
    QgsPointXY,
    QgsVectorLayer,
    QgsWkbTypes,
    QgsGeometry,
    QgsPoint,
)
from shapely.geometry import box as shapely_box
from math import sqrt


def find_nearest_node(graph: "nx.MultiDiGraph", lon: float, lat: float) -> Optional[int]:
    """
    Универсальная функция для поиска ближайшего узла в графе.
    Работает как с графами из OSM, так и с графами из слоя дорог.
    """
    if nx is None or len(graph.nodes()) == 0:
        return None
    
    min_dist = float('inf')
    nearest_node = None
    
    for node_id in graph.nodes():
        node_data = graph.nodes[node_id]
        node_lon = node_data.get('x')
        node_lat = node_data.get('y')
        
        if node_lon is None or node_lat is None:
            continue
        
        # Вычисляем расстояние по формуле гаверсинуса
        from math import radians, cos, sin, asin
        
        lat1, lon1 = radians(lat), radians(lon)
        lat2, lon2 = radians(node_lat), radians(node_lon)
        
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
        c = 2 * asin(sqrt(a))
        R = 6371000  # Радиус Земли в метрах
        dist = R * c
        
        if dist < min_dist:
            min_dist = dist
            nearest_node = node_id
    
    return nearest_node


def kmh_to_mm(kmh: float, precision: int = 2) -> float:
    """Км/ч -> м/мин"""
    if not isinstance(kmh, (int, float)):
        raise TypeError("Аргумент kmh должен иметь тип данных int или float")
    return round(kmh * 1000 / 60, precision)


def set_graph_travel_times(
    G: "nx.MultiDiGraph",
    speeds: List[float],
    morph_function: Optional[callable] = None,
    travel_time_field: str = "travel_time",
    speed_field: str = "maxspeed",
    highway_field: str = "highway",
    length_field: str = "length",
):
    """
    Проставляет скорости и время следования на рёбрах графа по типам дорог.
    speeds: список из 5 скоростей (см. комментарии ниже), км/ч или м/мин,
    при указании morph_function скорости будут преобразованы (например, км/ч -> м/мин).
    """
    if nx is None:
        raise RuntimeError("OSMnx/NetworkX недоступны. Установите пакет 'osmnx'.")
    if not isinstance(G, nx.MultiDiGraph):
        raise TypeError("Тип данных аргумента `G` должен быть nx.MultiDiGraph")
    if not isinstance(speeds, list) or len(speeds) != 5:
        raise ValueError("Аргумент `speeds` должен быть списком из 5 элементов")

    if G.graph.get("simplified", False):
        warnings.warn(
            "Граф был ранее упрощён. Рекомендуется задавать скорости до упрощения."
        )

    if morph_function is None:
        s1, s2, s3, s4, s5 = speeds
    else:
        s1, s2, s3, s4, s5 = [morph_function(kmh) for kmh in speeds]

    # Карта скоростей по highway-тегам OSM
    sp = {
        "trunk": s1,
        "trunk_link": s1,
        "motorway": s1,
        "motorway_link": s1,
        "primary": s2,
        "primary_link": s2,
        "secondary": s2,
        "secondary_link": s2,
        "unclassified": s2,
        "tertiary": s3,
        "tertiary_link": s3,
        "residential": s3,
        "living_street": s3,
        "road": s4,
        "service": s4,
        "track": s4,
        "footway": s5,
        "path": s5,
        "pedestrian": s5,
        "steps": s5,
        "cycleway": s5,
        "bridleway": s5,
        "corridor": s5,
    }

    # Установка скорости и времени на каждом ребре
    for u, v, k, data in G.edges(keys=True, data=True):
        road = data.get(highway_field, "other")
        length = data.get(length_field)
        if isinstance(road, list):
            road_speeds = [sp.get(rf, s5) for rf in road]
            speed = sum(road_speeds) / len(road_speeds)
        else:
            speed = sp.get(road, s5)

        data[speed_field] = speed
        # speed в м/мин, length в метрах → время в минутах
        data[travel_time_field] = (length / speed) if (speed and length) else None


def _get_cache_key(extent: QgsRectangle, buffer_m: float) -> str:
    """Генерирует ключ кеша на основе экстента и буфера"""
    key_str = f"{extent.xMinimum()}_{extent.yMinimum()}_{extent.xMaximum()}_{extent.yMaximum()}_{buffer_m}"
    return hashlib.md5(key_str.encode()).hexdigest()


def _get_cache_path() -> str:
    """Возвращает путь к директории кеша"""
    plugin_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cache_dir = os.path.join(plugin_dir, 'cache')
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


def load_graph_from_cache(cache_key: str) -> Optional["nx.MultiDiGraph"]:
    """Загружает граф из кеша"""
    if nx is None:
        return None
    
    cache_dir = _get_cache_path()
    cache_file = os.path.join(cache_dir, f"graph_{cache_key}.pkl")
    
    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'rb') as f:
                return pickle.load(f)
        except Exception:
            return None
    return None


def save_graph_to_cache(graph: "nx.MultiDiGraph", cache_key: str) -> bool:
    """Сохраняет граф в кеш"""
    if nx is None:
        return False
    
    cache_dir = _get_cache_path()
    cache_file = os.path.join(cache_dir, f"graph_{cache_key}.pkl")
    
    try:
        with open(cache_file, 'wb') as f:
            pickle.dump(graph, f)
        return True
    except Exception:
        return False


def build_graph_from_road_layer(
    road_layer: QgsVectorLayer,
    objects_layer: QgsVectorLayer,
    stations_layer: QgsVectorLayer,
    buffer_m: float = 500.0,
) -> Tuple["nx.MultiDiGraph", QgsCoordinateTransform, QgsCoordinateTransform]:
    """
    Строит граф дорог из существующего векторного слоя дорог.
    Возвращает граф и трансформации CRS: to_wgs84, from_wgs84.
    """
    if nx is None:
        raise RuntimeError("NetworkX недоступен. Установите пакет 'networkx'.")
    
    if road_layer.geometryType() != QgsWkbTypes.LineGeometry:
        raise ValueError("Слой дорог должен быть линейным слоем")
    
    # Трансформации координат
    crs_src = objects_layer.sourceCrs() if objects_layer is not None else QgsProject.instance().crs()
    crs_wgs = QgsCoordinateReferenceSystem.fromEpsgId(4326)
    
    to_wgs = QgsCoordinateTransform(crs_src, crs_wgs, QgsProject.instance())
    from_wgs = QgsCoordinateTransform(crs_wgs, crs_src, QgsProject.instance())
    
    # Объединённый экстент с буфером
    union_rect = QgsRectangle(objects_layer.extent())
    union_rect.combineExtentWith(stations_layer.extent())
    
    # Расширим экстент на buffer_m
    deg = buffer_m / 111000.0
    union_rect.grow(deg)
    
    # Создаём пустой граф
    G = nx.MultiDiGraph()
    
    # Получаем поля слоя дорог
    fields = road_layer.fields()
    highway_field_idx = None
    length_field_idx = None
    
    # Ищем поле highway или аналогичное
    for i, field in enumerate(fields):
        field_lower = field.name().lower()
        if field_lower in ['highway', 'road_type', 'type', 'тип', 'highway_type']:
            highway_field_idx = i
        if field_lower in ['length', 'длина']:
            length_field_idx = i
    
    # Обрабатываем все линии в слое дорог
    node_counter = 0
    node_coords = {}  # {(lon, lat): node_id}
    
    for feature in road_layer.getFeatures():
        geometry = feature.geometry()
        if geometry.isEmpty():
            continue
        
        # Проверяем, пересекается ли линия с экстентом
        if not geometry.boundingBox().intersects(union_rect):
            continue
        
        # Получаем тип дороги
        highway_type = "other"
        if highway_field_idx is not None:
            highway_val = feature.attribute(highway_field_idx)
            if highway_val:
                highway_type = str(highway_val)
        
        # Получаем длину
        length = geometry.length()
        if length_field_idx is not None:
            length_val = feature.attribute(length_field_idx)
            if length_val:
                length = float(length_val)
        
        # Преобразуем геометрию в WGS84
        geom_wgs = geometry
        if road_layer.sourceCrs() != crs_wgs:
            geom_wgs = QgsGeometry(geometry)
            geom_wgs.transform(to_wgs)
        
        # Получаем точки линии
        if geom_wgs.wkbType() == QgsWkbTypes.LineString:
            points = geom_wgs.asPolyline()
        elif geom_wgs.wkbType() == QgsWkbTypes.MultiLineString:
            points = []
            for line in geom_wgs.asMultiPolyline():
                points.extend(line)
        else:
            continue
        
        if len(points) < 2:
            continue
        
        # Создаём узлы и рёбра
        prev_node_id = None
        prev_point = None
        
        for i, point in enumerate(points):
            lon = point.x()
            lat = point.y()
            coord_key = (round(lon, 7), round(lat, 7))  # Округляем для совпадения узлов
            
            if coord_key not in node_coords:
                node_id = node_counter
                node_counter += 1
                node_coords[coord_key] = node_id
                G.add_node(node_id, x=lon, y=lat)
            else:
                node_id = node_coords[coord_key]
            
            if prev_node_id is not None and prev_point is not None:
                # Вычисляем длину сегмента в метрах (используя формулу гаверсинуса для точности)
                from math import radians, cos, sin, asin, sqrt
                
                lat1, lon1 = radians(prev_point.y()), radians(prev_point.x())
                lat2, lon2 = radians(lat), radians(lon)
                
                dlat = lat2 - lat1
                dlon = lon2 - lon1
                a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
                c = 2 * asin(sqrt(a))
                R = 6371000  # Радиус Земли в метрах
                segment_length = R * c
                
                G.add_edge(
                    prev_node_id,
                    node_id,
                    highway=highway_type,
                    length=segment_length
                )
            
            prev_node_id = node_id
            prev_point = point
    
    # Добавляем метаданные графа для совместимости с osmnx
    G.graph['crs'] = 'epsg:4326'
    
    return G, to_wgs, from_wgs


def build_graph_for_layers(
    objects_layer: QgsVectorLayer,
    stations_layer: QgsVectorLayer,
    buffer_m: float = 500.0,
    road_layer: Optional[QgsVectorLayer] = None,
    use_cache: bool = True,
) -> Tuple["nx.MultiDiGraph", QgsCoordinateTransform, QgsCoordinateTransform]:
    """
    Строит граф дорог OSM для объединённого экстента слоёв (с буфером).
    Может использовать существующий слой дорог или загружать из OSM.
    Поддерживает кеширование графа.
    
    Параметры:
    - objects_layer: слой объектов
    - stations_layer: слой пожарных станций
    - buffer_m: буфер вокруг экстента в метрах
    - road_layer: опциональный слой дорог (если None, загружается из OSM)
    - use_cache: использовать ли кеширование графа
    
    Возвращает граф и трансформации CRS: to_wgs84, from_wgs84.
    """
    # Трансформации координат
    crs_src = objects_layer.sourceCrs() if objects_layer is not None else QgsProject.instance().crs()
    crs_wgs = QgsCoordinateReferenceSystem.fromEpsgId(4326)

    to_wgs = QgsCoordinateTransform(crs_src, crs_wgs, QgsProject.instance())
    from_wgs = QgsCoordinateTransform(crs_wgs, crs_src, QgsProject.instance())

    # Объединённый экстент
    union_rect = QgsRectangle(objects_layer.extent())
    union_rect.combineExtentWith(stations_layer.extent())

    # Если передан слой дорог, используем его
    if road_layer is not None:
        return build_graph_from_road_layer(road_layer, objects_layer, stations_layer, buffer_m)

    # Проверяем кеш
    if use_cache:
        cache_key = _get_cache_key(union_rect, buffer_m)
        cached_graph = load_graph_from_cache(cache_key)
        if cached_graph is not None:
            return cached_graph, to_wgs, from_wgs

    # Загружаем из OSM
    if ox is None:
        raise RuntimeError("OSMnx недоступен. Установите пакет 'osmnx' или укажите слой дорог.")

    # Расширим экстент на buffer_m, для этого грубо переведём метры в градусы
    # (При малых буферах в городах достаточно, иначе увеличьте буфер)
    # 1 градус ~ 111км → 1 м ~ 1/111000 градуса
    deg = buffer_m / 111000.0

    # Точки экстента в WGS84
    ll = to_wgs.transform(QgsPointXY(union_rect.xMinimum(), union_rect.yMinimum()))
    ur = to_wgs.transform(QgsPointXY(union_rect.xMaximum(), union_rect.yMaximum()))
    south = min(ll.y(), ur.y()) - deg
    north = max(ll.y(), ur.y()) + deg
    west = min(ll.x(), ur.x()) - deg
    east = max(ll.x(), ur.x()) + deg

    # Строим граф для автомобильной сети
    # Используем построение по полигону для совместимости разных версий OSMnx
    polygon = shapely_box(west, south, east, north)
    G = ox.graph_from_polygon(polygon, network_type="drive")

    # Сохраняем в кеш
    if use_cache:
        cache_key = _get_cache_key(union_rect, buffer_m)
        save_graph_to_cache(G, cache_key)

    return G, to_wgs, from_wgs


# Значения по умолчанию (км/ч) согласно требованиям пользователя
# 1 - Магистральные городские дороги и улицы общегородского значения: 49
# 2 - Магистральные улицы районного значения: 37
# 3 - Улицы и дороги местного значения: 26
# 4 - Служебные проезды: 16
# 5 - Пешеходные/территории, пригодные для проезда: 5
DEFAULT_SPEEDS_KMH = [49.0, 37.0, 26.0, 16.0, 5.0]


