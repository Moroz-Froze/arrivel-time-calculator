from shapely.wkt import loads
from shapely.ops import unary_union
from .speed_management import SpeedManager 

def extract_polygons(source):
    wkt_strings = []
    for feature in source.getFeatures():
        wkt_strings.append(feature.geometry().asWkt())
    return unary_union([loads(wkt) for wkt in wkt_strings])

def calculate_travel_time(G, route, speed_limits):
    total_time = 0.0
    for i in range(len(route) - 1):
        edge_data = G.get_edge_data(route[i], route[i + 1])
        if edge_data:
            first_edge_key = next(iter(edge_data))
            road_type = edge_data[first_edge_key].get('highway', 'residential')
            distance = edge_data[first_edge_key].get('length', 0) / 1000  # Convert to kilometers
            if distance > 0:
                speed = speed_limits.get(road_type, 30)  # Default speed if type not found
                time_on_segment = (distance / speed) * 60  # Convert to minutes
                total_time += time_on_segment
    return total_time
