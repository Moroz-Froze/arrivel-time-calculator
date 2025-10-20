"""
Fire Response Time Analysis Plugin
Основной класс плагина для анализа времени прибытия пожарных подразделений
"""

from qgis.PyQt.QtCore import QSettings, QTranslator, QCoreApplication
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction
from qgis.core import QgsProcessingAlgorithm, QgsApplication
import os
import sys

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
        
        # Создание действия для панели инструментов
        self.action = QAction(
            QIcon(os.path.join(self.plugin_dir, 'icon.png')),
            u"Fire Response Analysis",
            self.iface.mainWindow())
        
        self.action.triggered.connect(self.run)
        self.iface.addPluginToVectorMenu(u"&Fire Analysis", self.action)
        self.iface.addVectorToolBarIcon(self.action)

    def unload(self):
        """Удаление плагина"""
        # Удаление провайдера обработки
        QgsApplication.processingRegistry().removeProvider(self.provider)
        
        # Удаление из меню и панели инструментов
        self.iface.removePluginVectorMenu(u"&Fire Analysis", self.action)
        self.iface.removeVectorToolBarIcon(self.action)

    def run(self):
        """Запуск диалога плагина"""
        from .fire_analysis_dialog import FireAnalysisDialog
        dlg = FireAnalysisDialog(self.iface)
        dlg.show()
        dlg.exec_()
