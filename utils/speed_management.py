
import networkx as nx
import warnings

class SpeedManager:
    default_speed_limits = {
        "trunk":          53,
        "trunk_link":     53,
        "motorway":       53,
        "motorway_link":  53,
        "primary":        40,
        "primary_link":   40,
        "secondary":      40,
        "secondary_link": 40,
        "unclassified":   40,
        "tertiary":       28.1,
        "tertiary_link":  28.1,
        "residential":    28.1,
        "living_street":  28.1,
        "road":           17.3,
        "service":        17.3,
        "track":          17.3,
        "footway":        5.4,
        "path":           5.4,
        "pedestrian":     5.4,
        "steps":          5.4,
        "cycleway":       5.4,
        "bridleway":      5.4,
        "corridor":      5.4,
    }

    def load_speed_limits(self, speed_matrix):
        speed_limits = self.default_speed_limits.copy()
        for row in speed_matrix:
            if isinstance(row, list) and len(row) >= 2:
                try:
                    road_type = str(row[0]).strip()
                    speed = float(row[1])
                    speed_limits[road_type] = speed
                except (ValueError, IndexError):
                    continue
        return speed_limits

    def kmh_to_mm(self,
                  kmh: float,
                  precision: int = 2) -> float:
        """
        Перевод: `километры в час` -> `метры в минуту`

        Аргументы
        ---------
        `kmh`: float
            Скорость в километрах в час

        `precision`: int
            Точность округления, знаков после запятой

        Возвращает
        ----------
        `mm`: float
            Скорость в метрах в минуту
        """
        if not isinstance(kmh, (int, float)):
            raise TypeError("Аргумент kmh должен иметь тип данных int или float")

        return round(kmh * 1000 / 60, precision)


    def set_graph_travel_times(self,
                        G: nx.MultiDiGraph,
                        speeds: list,
                        morph_function: callable = None,
                        travel_time_field: str = 'travel_time',
                        speed_field: str = 'maxspeed',
                        highway_speed = 'highway',
                        length_field = 'length',
                        ):
        """
        Добавление скоростей в граф

        Аргументы
        ---------
        `G`: networkx.MultiDiGraph
            Граф улично-дорожной сети
        `speeds`: list
            Список скоростей для 5 классов дорог:
            ```
            1 - Магистральные городские дороги и улицы общегородского значения
            2 - Магистральные улицы районного значения
            3 - Улицы и дороги местного значения
            4 - Служебные проезды: внутриквартальные, въездные, парковочные и т.д.
            5 - Пешеходные зоны и территории не являющиеся проезжей частью,
                но теоретически пригодные для передвижения пожарных автомобилей
            
            ВАЖНО! Единицы измерения: м/мин!

            Наиболее общий пример - использовать скорости по умолчанию (из graphs.settings):

            speeds = [kmh_to_mm(s) for s in DEFAULT_SPEEDS]
            set_graph_travel_times(G, speeds)

            или:
            set_graph_travel_times(G, DEFAULT_SPEEDS, kmh_to_mm)
            ```
        `morph_function`: callable
            Функция преобразования скоростей.
            Если указана, то будет применена к `speeds` как `morph_function(speeds)`
            Может быть использована для перевода `километры в час` -> `метры в минуту`
        `travel_time_field`: str = 'travel_time'
            Название поля в котором будет сохранено время следования
        `speed_field`: str ='maxspeed'
            Название поля в котором будет сохранено значение скорости следования

        Возвращает
        ----------
        None
        """

        # 0. Проверка входящих данных
        if not isinstance(G, nx.MultiDiGraph):
            raise TypeError('Тип данных аргумента `env` должен быть nx.MultiDiGraph')
        if not isinstance(speeds, list):
            raise ValueError('Тип данных аргумента `speeds` должен быть список')
        if len(speeds) != 5:
            raise ValueError('Аргумент `speeds` должен содержать строго 5 элементов!')

        if G.graph.get('simplified', False):
            warnings.warn("Граф был ранее упрощен! Оценка времени следования такого графа может повлечь неточности. " + \
                "Рекомендуется устанавливать время следования для неупрощенного графа " + \
                "и только после этого упрощать")

        # 1 Перевод скоростей в некоторые значения
        if morph_function is None:
            s1, s2, s3, s4, s5 = speeds
        else:
            s1, s2, s3, s4, s5 = [morph_function(kmh) for kmh in speeds]

        # 2 Установка скоростей для тегов OSM
        sp = {
                "trunk":          s1,           # Важные дороги, не являющиеся автомагистралями
                "trunk_link":     s1,           # Важные дороги, не являющиеся автомагистралями
                "motorway":       s1,           # Автомагистрали 
                "motorway_link":  s1,           # Автомагистрали 

                "primary":        s2,           # Автомобильные дороги регионального значения
                "primary_link":   s2,           # Автомобильные дороги регионального значения
                "secondary":      s2,           # Автомобильные дороги областного значения
                "secondary_link": s2,           # Автомобильные дороги областного значения
                "unclassified":   s2,           # Остальные автомобильные дороги местного значения, образующие соединительную сеть дорог.

                "tertiary":       s3,           # Более важные автомобильные дороги среди прочих автомобильных дорог местного значения
                "tertiary_link":  s3,           # Более важные автомобильные дороги среди прочих автомобильных дорог местного значения
                "residential":    s3,           # Дороги, которые проходят внутри жилых зон, а также используются для подъезда к ним
                "living_street":  s3,           # Жилые зоны и дворовые проезды

                "road":           s4,           # Линии, возможно, являющиеся дорогами. Временный тег, которым следует помечать линии до уточнения.
                "service":        s4,           # Служебные проезды: внутриквартальные, въездные, парковочные и т.д.
                "track":          s4,           # Дороги сельскохозяйственного назначения, лесные дороги, не ведущие к жилым или промышленным объектам, неофициальные грунтовки, козьи тропы

                "footway":        s5,           # Пешеходные дорожки, тротуары. 
                "path":           s5,           # Тропа (чаще всего, стихийная) использующаяся пешеходами, либо одним или несколькими видами транспорта, кроме четырехколесного (лыжи, снегоход, велосипед).
                "pedestrian":     s5,           # Для обозначения улиц городов (такого же класса как residential), выделенных для пешеходов.

                "steps":          s5,           # Лестницы, лестничные пролёты. 
                "cycleway":       s5,           # Велодорожка, обозначенная соответствующим дорожным знаком. 
                "bridleway":      s5,           # Дорожки для верховой езды.
                "corridor":       s5,           # Коридоры внутри крупных зданий
                "other":          s5,           # Все прочие - неопознанные
            }

        # 3. расчет и установка времени следования и скоростей
        attributes = {}
        for edge in G.edges:
            road = G.get_edge_data(*edge).get(highway_speed, 'other')
            length = G.get_edge_data(*edge).get(length_field)
            if isinstance(road, list):
                road_speeds = [sp.get(rf, s5) for rf in road]
                speed       = sum(road_speeds) / len(road_speeds)
            else:
                speed  = sp.get(road, s5)

            weight = length/speed
            attributes[*edge] = {travel_time_field: weight, speed_field: speed}

        nx.set_edge_attributes(G, attributes)