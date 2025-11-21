"""
Диалоговое окно для плагина анализа времени прибытия пожарных подразделений
"""

from qgis.PyQt import uic
from qgis.PyQt.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
                                 QLabel, QComboBox, QSpinBox, QDoubleSpinBox, 
                                 QTextEdit, QTabWidget, QWidget, QGroupBox, QFormLayout,
                                 QMessageBox, QProgressBar)
from qgis.PyQt.QtCore import Qt, QThread, pyqtSignal
from qgis.core import (QgsProject, QgsVectorLayer, QgsProcessingContext, QgsTask, 
                       QgsProcessing, QgsProcessingFeedback, QgsProcessingException)
from qgis.utils import iface
import os

from .algorithms.nearest_fire_station_algorithm import NearestFireStationAlgorithm
from .algorithms.response_time_routes_algorithm import ResponseTimeRoutesAlgorithm
from .algorithms.all_stations_response_algorithm import AllStationsResponseAlgorithm


class FireAnalysisDialog(QDialog):
    """Основное диалоговое окно плагина"""

    def __init__(self, iface):
        super(FireAnalysisDialog, self).__init__()
        self.iface = iface
        self.setWindowTitle("Анализ времени прибытия пожарных подразделений")
        self.setModal(True)
        self.resize(600, 500)
        
        # Инициализация алгоритмов
        self.nearest_algorithm = NearestFireStationAlgorithm()
        self.routes_algorithm = ResponseTimeRoutesAlgorithm()
        self.all_stations_algorithm = AllStationsResponseAlgorithm()
        
        self.setup_ui()
        self.populate_layers()

    def setup_ui(self):
        """Настройка пользовательского интерфейса"""
        layout = QVBoxLayout()
        
        # Создание вкладок
        self.tab_widget = QTabWidget()
        
        # Вкладка 1: Ближайшее подразделение
        self.tab1 = self.create_nearest_station_tab()
        self.tab_widget.addTab(self.tab1, "Ближайшее подразделение")
        
        # Вкладка 2: Маршруты времени прибытия
        self.tab2 = self.create_routes_tab()
        self.tab_widget.addTab(self.tab2, "Маршруты времени прибытия")
        
        # Вкладка 3: Анализ всех подразделений
        self.tab3 = self.create_all_stations_tab()
        self.tab_widget.addTab(self.tab3, "Анализ всех подразделений")
        
        layout.addWidget(self.tab_widget)

        # Группа: Скорости по типам дорог (км/ч)
        from qgis.PyQt.QtWidgets import QGroupBox, QFormLayout
        speeds_group = QGroupBox("Скорости по типам дорог (км/ч)")
        speeds_form = QFormLayout()
        self.road_speed_spinboxes = []
        # Порядок классов скоростей: 1..5
        labels = [
            "Магистральные городские и общегородского значения",
            "Магистральные улицы районного значения",
            "Улицы и дороги местного значения",
            "Служебные проезды, въездные, парковочные и т.д.",
            "Пешеходные зоны, пригодные для проезда",
        ]
        defaults = [49.0, 37.0, 26.0, 16.0, 5.0]
        for label, dv in zip(labels, defaults):
            sb = QDoubleSpinBox()
            sb.setRange(1.0, 200.0)
            sb.setValue(dv)
            sb.setSuffix(" км/ч")
            sb.setDecimals(1)
            self.road_speed_spinboxes.append(sb)
            speeds_form.addRow(label + ":", sb)
        speeds_group.setLayout(speeds_form)
        layout.addWidget(speeds_group)
        
        # Прогресс-бар
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        # Кнопки управления
        button_layout = QHBoxLayout()
        
        self.run_button = QPushButton("Выполнить анализ")
        self.run_button.clicked.connect(self.run_analysis)
        button_layout.addWidget(self.run_button)
        
        self.close_button = QPushButton("Закрыть")
        self.close_button.clicked.connect(self.close)
        button_layout.addWidget(self.close_button)
        
        layout.addLayout(button_layout)
        self.setLayout(layout)

    def create_nearest_station_tab(self):
        """Создание вкладки для анализа ближайшего подразделения"""
        widget = QWidget()
        layout = QFormLayout()
        
        # Выбор слоя объектов
        self.objects_layer_combo = QComboBox()
        self.objects_layer_combo.setMinimumWidth(200)
        layout.addRow("Слой объектов:", self.objects_layer_combo)
        
        # Выбор слоя пожарных станций
        self.stations_layer_combo = QComboBox()
        self.stations_layer_combo.setMinimumWidth(200)
        layout.addRow("Слой пожарных станций:", self.stations_layer_combo)
        
        # Средняя скорость — удалено, используем скорости по типам дорог
        
        widget.setLayout(layout)
        return widget

    def create_routes_tab(self):
        """Создание вкладки для маршрутов времени прибытия"""
        widget = QWidget()
        layout = QFormLayout()
        
        # Выбор слоя объектов
        self.routes_objects_combo = QComboBox()
        self.routes_objects_combo.setMinimumWidth(200)
        layout.addRow("Слой объектов:", self.routes_objects_combo)
        
        # Выбор слоя пожарных станций
        self.routes_stations_combo = QComboBox()
        self.routes_stations_combo.setMinimumWidth(200)
        layout.addRow("Слой пожарных станций:", self.routes_stations_combo)
        
        # Средняя скорость — удалено, используем скорости по типам дорог
        
        # Тип маршрутов
        self.route_type_combo = QComboBox()
        self.route_type_combo.addItems([
            "Только к ближайшей станции",
            "Ко всем станциям",
            "Ко всем станциям в радиусе времени"
        ])
        layout.addRow("Тип маршрутов:", self.route_type_combo)
        
        # Пороговое время
        self.time_threshold_spinbox = QDoubleSpinBox()
        self.time_threshold_spinbox.setRange(1.0, 300.0)
        self.time_threshold_spinbox.setValue(30.0)
        self.time_threshold_spinbox.setSuffix(" мин")
        layout.addRow("Пороговое время:", self.time_threshold_spinbox)
        
        widget.setLayout(layout)
        return widget

    def create_all_stations_tab(self):
        """Создание вкладки для анализа всех подразделений"""
        widget = QWidget()
        layout = QFormLayout()
        
        # Выбор слоя объектов
        self.all_objects_combo = QComboBox()
        self.all_objects_combo.setMinimumWidth(200)
        layout.addRow("Слой объектов:", self.all_objects_combo)
        
        # Выбор слоя пожарных станций
        self.all_stations_combo = QComboBox()
        self.all_stations_combo.setMinimumWidth(200)
        layout.addRow("Слой пожарных станций:", self.all_stations_combo)
        
        # Средняя скорость — удалено, используем скорости по типам дорог
        
        # Ранг пожара
        self.fire_rank_combo = QComboBox()
        self.fire_rank_combo.addItems([
            "1-й ранг (1-2 подразделения)",
            "2-й ранг (3-4 подразделения)",
            "3-й ранг (5-6 подразделений)",
            "4-й ранг (7-8 подразделений)",
            "5-й ранг (9+ подразделений)"
        ])
        layout.addRow("Ранг пожара:", self.fire_rank_combo)
        
        # Максимальное количество станций
        self.max_stations_spinbox = QSpinBox()
        self.max_stations_spinbox.setRange(1, 20)
        self.max_stations_spinbox.setValue(6)
        layout.addRow("Максимум станций:", self.max_stations_spinbox)
        
        widget.setLayout(layout)
        return widget

    def populate_layers(self):
        """Заполнение списков слоев"""
        layers = QgsProject.instance().mapLayers().values()
        vector_layers = [layer for layer in layers if isinstance(layer, QgsVectorLayer)]
        
        for layer in vector_layers:
            layer_name = layer.name()
            
            # Для точечных и полигональных слоев
            if layer.geometryType() in [0, 2]:  # Point или Polygon
                self.objects_layer_combo.addItem(layer_name, layer)
                self.routes_objects_combo.addItem(layer_name, layer)
                self.all_objects_combo.addItem(layer_name, layer)
            
            # Для точечных слоев (пожарные станции)
            if layer.geometryType() == 0:  # Point
                self.stations_layer_combo.addItem(layer_name, layer)
                self.routes_stations_combo.addItem(layer_name, layer)
                self.all_stations_combo.addItem(layer_name, layer)

    # Удалены вспомогательные методы выбора полей: имя и тип подразделений больше не задаются вручную

    def get_layer_by_name(self, name):
        """Получение слоя по имени"""
        layers = QgsProject.instance().mapLayers().values()
        for layer in layers:
            if layer.name() == name:
                return layer
        return None

    def run_analysis(self):
        """Запуск анализа в зависимости от выбранной вкладки"""
        current_tab = self.tab_widget.currentIndex()
        
        if current_tab == 0:  # Ближайшее подразделение
            self.run_nearest_station_analysis()
        elif current_tab == 1:  # Маршруты времени прибытия
            self.run_routes_analysis()
        elif current_tab == 2:  # Анализ всех подразделений
            self.run_all_stations_analysis()

    def run_nearest_station_analysis(self):
        """Запуск анализа ближайшего подразделения"""
        try:
            # Получение параметров
            objects_layer = self.objects_layer_combo.currentData()
            stations_layer = self.stations_layer_combo.currentData()
            speeds = [sb.value() for sb in self.road_speed_spinboxes]
            
            if not objects_layer or not stations_layer:
                QMessageBox.warning(self, "Ошибка", "Пожалуйста, заполните все обязательные поля")
                return
            
            # Подготовка параметров для алгоритма
            parameters = {
                'OBJECTS_LAYER': objects_layer,
                'FIRE_STATIONS_LAYER': stations_layer,
                'ROAD_SPEEDS_KMH': speeds,
                'USE_CACHE': 0,  # Использовать кеширование по умолчанию
                'OUTPUT_LAYER': QgsProcessing.TEMPORARY_OUTPUT
            }
            
            # Запуск алгоритма
            self.run_processing_algorithm(self.nearest_algorithm, parameters)
            
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Произошла ошибка: {str(e)}")

    def run_routes_analysis(self):
        """Запуск анализа маршрутов"""
        try:
            # Получение параметров
            objects_layer = self.routes_objects_combo.currentData()
            stations_layer = self.routes_stations_combo.currentData()
            speeds = [sb.value() for sb in self.road_speed_spinboxes]
            route_type = self.route_type_combo.currentIndex()
            time_threshold = self.time_threshold_spinbox.value()
            
            if not objects_layer or not stations_layer:
                QMessageBox.warning(self, "Ошибка", "Пожалуйста, заполните все обязательные поля")
                return
            
            # Подготовка параметров для алгоритма
            parameters = {
                'OBJECTS_LAYER': objects_layer,
                'FIRE_STATIONS_LAYER': stations_layer,
                'ROAD_SPEEDS_KMH': speeds,
                'USE_CACHE': 0,  # Использовать кеширование по умолчанию
                'ROUTE_TYPE': route_type,
                'TIME_THRESHOLD': time_threshold,
                'OUTPUT_LAYER': QgsProcessing.TEMPORARY_OUTPUT
            }
            
            # Запуск алгоритма
            self.run_processing_algorithm(self.routes_algorithm, parameters)
            
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Произошла ошибка: {str(e)}")

    def run_all_stations_analysis(self):
        """Запуск анализа всех подразделений"""
        try:
            # Получение параметров
            objects_layer = self.all_objects_combo.currentData()
            stations_layer = self.all_stations_combo.currentData()
            speeds = [sb.value() for sb in self.road_speed_spinboxes]
            fire_rank = self.fire_rank_combo.currentIndex()
            max_stations = self.max_stations_spinbox.value()
            
            if not objects_layer or not stations_layer:
                QMessageBox.warning(self, "Ошибка", "Пожалуйста, заполните все обязательные поля")
                return
            
            # Подготовка параметров для алгоритма
            parameters = {
                'OBJECTS_LAYER': objects_layer,
                'FIRE_STATIONS_LAYER': stations_layer,
                'ROAD_SPEEDS_KMH': speeds,
                'USE_CACHE': 0,  # Использовать кеширование по умолчанию
                'FIRE_RANK': fire_rank,
                'MAX_STATIONS': max_stations,
                'OUTPUT_LAYER': QgsProcessing.TEMPORARY_OUTPUT
            }
            
            # Запуск алгоритма
            self.run_processing_algorithm(self.all_stations_algorithm, parameters)
            
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Произошла ошибка: {str(e)}")

    def run_processing_algorithm(self, algorithm, parameters):
        """Запуск алгоритма обработки"""
        context = QgsProcessingContext()
        context.setProject(QgsProject.instance())
        feedback = self.create_feedback()
        
        self.progress_bar.setVisible(True)
        self.run_button.setEnabled(False)
        
        try:
            # Используем правильный метод run() вместо прямого вызова processAlgorithm
            result = algorithm.run(parameters, context, feedback)
            
            # Получение выходного слоя из результата
            output_key = getattr(algorithm, 'OUTPUT_LAYER', 'OUTPUT_LAYER')
            layer_id = result.get(output_key) if result else None
            
            if layer_id:
                layer = context.getMapLayer(layer_id)
                if layer is None:
                    # Попробуем получить из проекта
                    layer = QgsProject.instance().mapLayer(layer_id)
                
                if layer is not None and layer.isValid():
                    layer.setName(algorithm.displayName())
                    if layer not in QgsProject.instance().mapLayers().values():
                        QgsProject.instance().addMapLayer(layer)
                    QMessageBox.information(self, "Успех", "Анализ завершен успешно!")
                else:
                    QMessageBox.warning(self, "Ошибка", f"Не удалось получить выходной слой. ID: {layer_id}")
            else:
                QMessageBox.warning(self, "Ошибка", "Не удалось получить идентификатор выходного слоя")
                        
        except QgsProcessingException as e:
            QMessageBox.critical(self, "Ошибка обработки", f"Ошибка выполнения алгоритма: {str(e)}")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Произошла ошибка: {str(e)}")
        finally:
            self.progress_bar.setVisible(False)
            self.run_button.setEnabled(True)

    def create_feedback(self):
        """Создание объекта обратной связи для отслеживания прогресса"""
        from qgis.core import QgsProcessingFeedback
        
        class DialogFeedback(QgsProcessingFeedback):
            def __init__(self, progress_bar):
                super().__init__()
                self.progress_bar = progress_bar
                
            def setProgress(self, progress):
                self.progress_bar.setValue(progress)
                
        return DialogFeedback(self.progress_bar)