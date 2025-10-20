"""
Утилиты для построения графа дорог OSM и расчёта времени следования
с учётом типов дорог и скоростей для пожарной техники.
"""

from typing import List, Tuple, Optional

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
)
from shapely.geometry import box as shapely_box


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


def build_graph_for_layers(
    objects_layer: QgsVectorLayer,
    stations_layer: QgsVectorLayer,
    buffer_m: float = 500.0,
) -> Tuple["nx.MultiDiGraph", QgsCoordinateTransform, QgsCoordinateTransform]:
    """
    Строит граф дорог OSM для объединённого экстента слоёв (с буфером).
    Возвращает граф и трансформации CRS: to_wgs84, from_wgs84.
    """
    if ox is None:
        raise RuntimeError("OSMnx недоступен. Установите пакет 'osmnx'.")

    # Трансформации координат
    crs_src = objects_layer.sourceCrs() if objects_layer is not None else QgsProject.instance().crs()
    crs_wgs = QgsCoordinateReferenceSystem.fromEpsgId(4326)

    to_wgs = QgsCoordinateTransform(crs_src, crs_wgs, QgsProject.instance())
    from_wgs = QgsCoordinateTransform(crs_wgs, crs_src, QgsProject.instance())

    # Объединённый экстент
    union_rect = QgsRectangle(objects_layer.extent())
    union_rect.combineExtentWith(stations_layer.extent())

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

    return G, to_wgs, from_wgs


# Значения по умолчанию (км/ч) согласно требованиям пользователя
# 1 - Магистральные городские дороги и улицы общегородского значения: 49
# 2 - Магистральные улицы районного значения: 37
# 3 - Улицы и дороги местного значения: 26
# 4 - Служебные проезды: 16
# 5 - Пешеходные/территории, пригодные для проезда: 5
DEFAULT_SPEEDS_KMH = [49.0, 37.0, 26.0, 16.0, 5.0]


