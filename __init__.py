"""
Fire Response Time Analysis Plugin for QGIS
Анализ времени прибытия пожарных подразделений

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.
"""

def classFactory(iface):
    """Load FireAnalysisPlugin class from file fire_analysis_plugin.
    
    :param iface: A QGIS interface instance.
    :type iface: QgsInterface
    """
    from .fire_analysis_plugin import FireAnalysisPlugin
    return FireAnalysisPlugin(iface)
