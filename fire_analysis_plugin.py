"""
Fire Response Time Analysis Plugin
Основной класс плагина для анализа времени прибытия пожарных подразделений
"""

from qgis.PyQt.QtCore import QSettings, QTranslator, QCoreApplication
from qgis.core import QgsApplication
import os

from .fire_response_analysis_provider import FireResponseAnalysisProvider


class FireAnalysisPlugin:
    """Основной класс плагина"""

    def __init__(self, iface):
        """Инициализация плагина"""
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        
        # Инициализация переводчика
        locale = QSettings().value('locale/userLocale')[0:2]
        locale_path = os.path.join(
            self.plugin_dir,
            'i18n',
            'FireAnalysisPlugin_{}.qm'.format(locale))

        if os.path.exists(locale_path):
            self.translator = QTranslator()
            self.translator.load(locale_path)
            QCoreApplication.installTranslator(self.translator)

        # Инициализация провайдера обработки
        self.provider = FireResponseAnalysisProvider()

    def initGui(self):
        """Создание меню и панели инструментов"""
        # Добавление провайдера обработки
        QgsApplication.processingRegistry().addProvider(self.provider)

    def unload(self):
        """Удаление плагина"""
        # Удаление провайдера обработки
        QgsApplication.processingRegistry().removeProvider(self.provider)
