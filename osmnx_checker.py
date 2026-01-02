"""
Утилита для проверки наличия библиотеки osmnx и предложения установки
"""

import os
import subprocess
import sys
from qgis.PyQt.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
                                 QLabel, QMessageBox)
from qgis.PyQt.QtCore import Qt


def check_osmnx_available():
    """Проверяет наличие библиотеки osmnx"""
    try:
        import osmnx
        return True
    except ImportError:
        return False


def show_osmnx_install_dialog(iface=None, parent=None):
    """Показывает диалог с предложением установить osmnx"""
    # Получаем родительское окно
    if parent is None:
        # Пытаемся получить через iface
        if iface is not None:
            try:
                parent = iface.mainWindow()
            except:
                pass
        
        # Если не получили через iface, пытаемся через qgis.utils
        if parent is None:
            try:
                from qgis.utils import iface as qgis_iface
                if qgis_iface:
                    parent = qgis_iface.mainWindow()
            except:
                pass
        
        # Если все еще не получили, ищем через QApplication
        if parent is None:
            try:
                from qgis.PyQt.QtWidgets import QApplication
                app = QApplication.instance()
                if app:
                    # Пытаемся найти главное окно QGIS
                    for widget in app.topLevelWidgets():
                        widget_name = getattr(widget, 'objectName', lambda: '')()
                        if widget_name == 'QgisApp' or 'QGIS' in str(type(widget)):
                            parent = widget
                            break
                    # Если не нашли, берем активное окно
                    if parent is None:
                        parent = app.activeWindow()
            except Exception:
                pass
    
    # Создаем и показываем диалог
    try:
        dialog = OSMnxInstallDialog(iface, parent)
        # Убеждаемся, что диалог виден
        dialog.raise_()
        dialog.activateWindow()
        return dialog.exec_()
    except Exception as e:
        # Если не удалось показать диалог, показываем простое сообщение
        try:
            from qgis.PyQt.QtWidgets import QMessageBox, QApplication
            app = QApplication.instance()
            if app:
                msg = QMessageBox(parent)
                msg.setWindowTitle("Установка библиотеки OSMnx")
                msg.setText(
                    "Для работы алгоритма необходима библиотека OSMnx.\n\n"
                    "Установите её через OSGeo4W Shell:\n"
                    "python -m pip install \"osmnx>=1.4,<2.0\" \"networkx>=2.6,<3.0\""
                )
                msg.exec_()
        except:
            pass
        return 0


class OSMnxInstallDialog(QDialog):
    """Диалог для предложения установки osmnx"""
    
    def __init__(self, iface=None, parent=None):
        super(OSMnxInstallDialog, self).__init__(parent)
        self.iface = iface
        self.setWindowTitle("Установка библиотеки OSMnx")
        self.setModal(True)
        self.resize(400, 150)
        
        # Устанавливаем флаги окна для правильного отображения
        self.setWindowFlags(Qt.Dialog | Qt.WindowTitleHint | Qt.WindowCloseButtonHint)
        
        self.setup_ui()
    
    def setup_ui(self):
        """Настройка пользовательского интерфейса"""
        layout = QVBoxLayout()
        
        # Текст сообщения
        message_label = QLabel(
            "Для работы алгоритма необходима библиотека OSMnx, которая не установлена.\n\n"
            "Желаете установить библиотеку?"
        )
        message_label.setWordWrap(True)
        layout.addWidget(message_label)
        
        # Кнопки
        button_layout = QHBoxLayout()
        
        self.yes_button = QPushButton("Да")
        self.yes_button.clicked.connect(self.install_osmnx)
        button_layout.addWidget(self.yes_button)
        
        self.no_button = QPushButton("Нет")
        self.no_button.clicked.connect(self.reject)
        button_layout.addWidget(self.no_button)
        
        layout.addLayout(button_layout)
        self.setLayout(layout)
    
    def install_osmnx(self):
        """Запускает установку osmnx через bat-файл"""
        # Получаем путь к директории плагина (где находится bat-файл)
        plugin_dir = os.path.dirname(os.path.abspath(__file__))
        bat_file = os.path.join(plugin_dir, 'install_osmnx.bat')
        
        if not os.path.exists(bat_file):
            QMessageBox.warning(
                self,
                "Ошибка",
                f"Файл установки не найден: {bat_file}\n\n"
                "Пожалуйста, установите osmnx вручную."
            )
            return
        
        try:
            # Запускаем bat-файл в новом окне командной строки
            # Используем cmd /c для запуска в отдельном окне
            subprocess.Popen(
                ['cmd', '/c', 'start', 'cmd', '/k', bat_file],
                shell=False
            )
            QMessageBox.information(
                self,
                "Установка запущена",
                "Установка osmnx запущена в отдельном окне командной строки.\n\n"
                "После завершения установки перезапустите QGIS."
            )
            self.accept()
        except Exception as e:
            QMessageBox.critical(
                self,
                "Ошибка",
                f"Не удалось запустить установку:\n{str(e)}\n\n"
                "Попробуйте запустить bat-файл вручную из OSGeo4W Shell."
            )

