"""
Fire Response Time Analysis Plugin
Основной класс плагина для анализа времени прибытия пожарных подразделений
"""

from qgis.PyQt.QtCore import QSettings, QTranslator, QCoreApplication
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction
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
        
        # Действие для меню плагинов
        self.install_libs_action = None

    def initGui(self):
        """Создание меню и панели инструментов"""
        # Добавление провайдера обработки
        QgsApplication.processingRegistry().addProvider(self.provider)
        
        # Создание действия для установки библиотек в меню плагинов
        self.install_libs_action = QAction(
            QIcon(os.path.join(self.plugin_dir, 'icons', 'icon.png')),
            u"Установка библиотек (OSMnx)",
            self.iface.mainWindow())
        
        self.install_libs_action.triggered.connect(self.show_install_dialog)
        self.iface.addPluginToMenu(u"&Fire Analysis", self.install_libs_action)

    def unload(self):
        """Удаление плагина"""
        # Удаление провайдера обработки
        QgsApplication.processingRegistry().removeProvider(self.provider)
        
        # Удаление действия из меню
        if self.install_libs_action:
            self.iface.removePluginMenu(u"&Fire Analysis", self.install_libs_action)
            self.install_libs_action = None
    
    def show_install_dialog(self):
        """Показывает диалог установки библиотек"""
        from .osmnx_checker import show_osmnx_install_dialog
        show_osmnx_install_dialog(self.iface, self.iface.mainWindow())
