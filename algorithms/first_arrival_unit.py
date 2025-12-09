"""
Алгоритм определения первого прибывающего подразделения.
"""

__author__    = 'Малютин О.С.'
__date__      = '2025-12-09'
__copyright__ = '(C) 2025 by SPSA'

__revision__  = '$Format:%H$'


import inspect
import os

from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtGui import QIcon

from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsField,
    QgsProcessingException,
    QgsProcessingAlgorithm,
    QgsProcessing,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterFileDestination,
    QgsProcessingParameterField,
)

try:
    import geopandas as gpd
    import pandas as pd
    GPD_AVAILABLE = True
except ImportError:
    GPD_AVAILABLE = False


class FirstArrivalUnitAlgorithm(QgsProcessingAlgorithm):
    """
    Алгоритм определения первого прибывающего подразделения.

    Принимает слой матрицы прибытия и слой подразделений.
    На выходе создает новый слой застройки, в котором вместо
    столбцов с временами прибытия всех подразделений,
    добавлены два столбца: название первого прибывающего
    подразделения и его время прибытия.
    """

    # Параметры входных данных
    ARRIVAL_MATRIX   = 'ARRIVAL_MATRIX'        # Слой матрицы прибытия
    FIRE_UNITS       = 'FIRE_UNITS'            # Слой подразделений
    UNITS_NAME_FIELD = 'UNITS_NAME_FIELD'      # Поле названия подразделения
    OUTPUT           = 'OUTPUT'                # Выходной слой

    def tr(self, string):
        """
        Возвращает перевод для self.tr().
        """
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return FirstArrivalUnitAlgorithm()

    def name(self):
        """
        Название алгоритма
        """
        return 'first_arrival_unit'

    def displayName(self):
        """
        Отображаемое название алгоритма
        """
        return self.tr('Время прибытия первого подразделения')

    def group(self):
        """
        Возвращает название группы, к которой принадлежит этот алгоритм.
        """
        return self.tr('Анализ прибытия')

    def groupId(self):
        """
        Возвращает уникальный идентификатор группы, к которой принадлежит этот алгоритм.
        """
        return 'ARRIVAL_ANALYSIS'

    def shortHelpString(self):
        """
        Возвращает краткое описание алгоритма
        """
        return self.tr("""
            Алгоритм определения первого прибывающего подразделения пожарной охраны.

            Принимает:
            - Слой матрицы прибытия (полученный с помощью алгоритма "Матрица прибытия всех подразделений")
            - Слой пожарных подразделений

            Результат:
            - Новый векторный слой застройки с двумя столбцами:
              * "first_unit" - название первого прибывающего подразделения
              * "first_time" - время прибытия первого подразделения

            Алгоритм проходит по всем объектам в слое матрицы прибытия и для каждого
            определяет подразделение с минимальным временем прибытия, исключая значения NULL/NaN.

            Выходной файл сохраняется в формате Geopackage (.gpkg) и автоматически
            добавляется на карту как новый слой.
        """)

    def icon(self):
        """
        Возвращает иконку алгоритма
        """
        cmd_folder = os.path.split(inspect.getfile(inspect.currentframe()))[0]
        icon_path = os.path.join(cmd_folder, '..', 'icons', 'nearest_fire_station_algorithm_icon.png')
        icon_path = os.path.normpath(icon_path)
        if os.path.exists(icon_path):
            return QIcon(icon_path)
        else:
            return QIcon()

    def initAlgorithm(self, config=None):
        """
        Здесь указываются настройки алгоритма - входы и выходы.
        """

        # Слой матрицы прибытия
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.ARRIVAL_MATRIX,
                self.tr('Слой матрицы прибытия'),
                [QgsProcessing.TypeVectorAnyGeometry],
                defaultValue='Матрица прибытия',
                optional=False
            )
        )

        # Слой пожарных подразделений
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.FIRE_UNITS,
            self.tr('Слой пожарных подразделений'),
            [QgsProcessing.TypeVectorPoint],
            defaultValue='Подразделения',
            optional=False
        ))

        # Поле названия подразделения
        self.addParameter(QgsProcessingParameterField(
            self.UNITS_NAME_FIELD,
            self.tr('Поле названия подразделения'),
            parentLayerParameterName=self.FIRE_UNITS,
            type=QgsProcessingParameterField.String,
            defaultValue='name',
            optional=False
        ))

        # Выходной файл
        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.OUTPUT,
                self.tr('Первое прибывшее подразделение (новый слой)'),
                'файл Geopackage (*.gpkg)',
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        """
        Основная логика алгоритма
        """

        # Проверяем доступность geopandas
        if not GPD_AVAILABLE:
            raise QgsProcessingException(
                self.tr('Необходимо установить библиотеки: geopandas, pandas')
            )

        # Получаем входные параметры
        arrival_matrix_source = self.parameterAsSource(parameters, self.ARRIVAL_MATRIX, context)
        fire_units_source     = self.parameterAsSource(parameters, self.FIRE_UNITS, context)
        units_name_field      = self.parameterAsString(parameters, self.UNITS_NAME_FIELD, context)
        output_file           = self.parameterAsFile(parameters, self.OUTPUT, context)

        # Начинаем процесс обработки
        feedback.setProgressText('Чтение входных данных...')
        feedback.setProgress(5)

        # Формируем слой подразделений
        units_gdf = gpd.GeoDataFrame.from_features(
            list(fire_units_source.getFeatures()),
            crs=fire_units_source.sourceCrs().authid()
        )

        # Загружаем слой матрицы прибытия в GeoDataFrame
        arrival_gdf = gpd.GeoDataFrame.from_features(
            list(arrival_matrix_source.getFeatures()),
            crs=arrival_matrix_source.sourceCrs().authid()
        )

        feedback.setProgress(20)
        feedback.setProgressText('Обработка матрицы прибытия...')

        # Определяем столбцы, содержащие времена прибытия
        units_names = list(units_gdf[units_name_field].unique())

        # Для каждого объекта определяем первое прибывающее подразделение
        first_units = []
        first_times = []

        # Обработка с прогрессом
        total_features = len(arrival_gdf)
        step = max(1, total_features // 100)  # Обновляем прогресс каждые 1% или чаще

        for idx, row in arrival_gdf.iterrows():
            # Получаем значения времён прибытия для текущего объекта
            arrival_times = row[units_names]

            # Убираем значения NaN/None
            valid_times = arrival_times.dropna()

            if len(valid_times) > 0:
                # Находим минимальное время прибытия
                min_time = valid_times.min()
                # Находим имя подразделения с минимальным временем
                first_unit = valid_times.idxmin()
            else:
                # Если нет валидных значений, устанавливаем пустые значения
                min_time = None
                first_unit = None


            first_units.append(first_unit)
            first_times.append(min_time)

            # Обновляем прогресс
            if idx % step == 0:
                progress = 40 + int((idx / total_features) * 55)
                feedback.setProgress(progress)
                if feedback.isCanceled():
                    break

        # Добавляем новые столбцы в GeoDataFrame
        arrival_gdf['first_unit'] = first_units
        arrival_gdf['first_time'] = first_times
        feedback.pushDebugInfo('Добавлено поле "first_unit" содержащее название первого прибывшего подразделения')
        feedback.pushDebugInfo('Добавлено поле "first_time" содержащее время прибытия первого подразделения')
        feedback.pushDebugInfo('Поля времен прибытия подразделений удалены.')

        # Удаляем колонки с временами прибытия
        arrival_gdf = arrival_gdf.drop(columns=units_names)
        feedback.setProgress(95)

        # Сохраняем результат в выходной файл
        feedback.setProgressText('Сохранение результата...')
        arrival_gdf.to_file(output_file)

        # Добавляем полученный слой на карту
        result_layer = QgsVectorLayer(output_file, 'Первое прибывшее подразделение', 'ogr')
        if result_layer.isValid():
            QgsProject.instance().addMapLayer(result_layer)

        feedback.setProgress(100)
        feedback.setProgressText('Готово!')

        return {self.OUTPUT: output_file}