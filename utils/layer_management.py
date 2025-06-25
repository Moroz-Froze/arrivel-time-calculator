from qgis.core import QgsVectorLayer, QgsField, QgsFeature, QgsGeometry, QgsPointXY
from PyQt5.QtCore import QVariant

def create_route_layer():
    layer_name = 'Routes'
    layer = QgsVectorLayer('LineString?crs=EPSG:4326', layer_name, 'memory')
    provider = layer.dataProvider()
    provider.addAttributes([
        QgsField("Travel Time", QVariant.Double),
        QgsField("Start Name", QVariant.String),
        QgsField("End Name", QVariant.String)
    ])
    layer.updateFields()
    return layer

def display_route(layer, route, travel_time, start_name, end_name, G):
    coords = [(G.nodes[n]['x'], G.nodes[n]['y']) for n in route]
    geometry = QgsGeometry.fromPolylineXY([QgsPointXY(*coord) for coord in coords])

    feature = QgsFeature()
    feature.setGeometry(geometry)
    feature.setAttributes([travel_time, start_name, end_name]) 

    provider = layer.dataProvider()
    provider.addFeature(feature)
    layer.updateExtents()
    layer.triggerRepaint()

def create_point_layer(fields, crs_string):
    """
    Создает точечный слой с указанными полями и системой координат
    
    :param fields: QgsFields - поля слоя
    :param crs_string: str - строка CRS (например, 'EPSG:4326')
    :return: QgsVectorLayer - созданный слой
    """
    layer = QgsVectorLayer(f"Point?crs={crs_string}", "Arrival Times", "memory")
    provider = layer.dataProvider()
    
    # Добавляем поля
    provider.addAttributes(fields)
    layer.updateFields()
    
    return layer

def display_point(layer, point_geometry, travel_time, start_name, end_name):
    feature = QgsFeature()
    feature.setGeometry(point_geometry)
    feature.setAttributes([travel_time, start_name, end_name])

    provider = layer.dataProvider()
    provider.addFeature(feature)
    layer.updateExtents()
    layer.triggerRepaint()