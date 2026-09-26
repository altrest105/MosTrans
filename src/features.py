import math

import pandas as pd


EARTH_RADIUS_M = 6_371_000
HISTORY_WINDOW_MINUTES = 10
STOPPED_SPEED_THRESHOLD_KMH = 1.0

FEATURE_NAMES = (
    "cur_dev_s",
    "horizon_min",
    "hour",
    "last_speed",
    "telemetry_age_s",
    "mean_speed_10m",
    "max_speed_10m",
    "stopped_share_10m",
    "gps_points_10m",
    "distance_to_target_m",
)


def parse_point(value: str) -> tuple[float, float]:
    """
    Преобразовать WKT-точку в координаты.

    Пример:
    POINT (37.70782708 55.68567388)
    -> (37.70782708, 55.68567388)
    """

    value = value.strip()

    if not value.startswith("POINT (") or not value.endswith(")"):
        raise ValueError(
            f"Некорректный формат координат: {value}"
        )

    coordinates = (
        value
        .removeprefix("POINT (")
        .removesuffix(")")
    )

    lon, lat = coordinates.split()

    return float(lon), float(lat)


def haversine_m(
    lon1: float,
    lat1: float,
    lon2: float,
    lat2: float,
) -> float:
    """Посчитать расстояние между двумя GPS-точками в метрах."""

    lon1_rad = math.radians(lon1)
    lat1_rad = math.radians(lat1)
    lon2_rad = math.radians(lon2)
    lat2_rad = math.radians(lat2)

    dlon = lon2_rad - lon1_rad
    dlat = lat2_rad - lat1_rad

    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1_rad)
        * math.cos(lat2_rad)
        * math.sin(dlon / 2) ** 2
    )

    c = 2 * math.asin(math.sqrt(a))

    return EARTH_RADIUS_M * c


def get_vehicle_history(
    traffic: pd.DataFrame,
    tr_id: int,
    prediction_time: pd.Timestamp,
) -> pd.DataFrame:
    """
    Получить историю ТС, доступную на момент прогноза.

    Телеметрия после prediction_time исключается,
    чтобы модель не использовала данные из будущего.
    """

    history = traffic[
        (traffic["tr_id"] == tr_id)
        & (traffic["event_time"] <= prediction_time)
    ].copy()

    return history.sort_values("event_time")


def get_valid_gps(
    history: pd.DataFrame,
) -> pd.DataFrame:
    """Оставить только телеметрию с валидными GPS-координатами."""

    return history[
        history["location_valid"]
        & history["lat"].notna()
        & history["lon"].notna()
    ].copy()


def build_features(
    sample: pd.Series,
    traffic: pd.DataFrame,
    schedule: pd.DataFrame,
) -> dict:
    """
    Построить признаки для одной прогнозной точки.

    Используются только данные, доступные
    к моменту формирования прогноза T.
    """

    tr_id = sample["tr_id"]
    prediction_time = sample["T"]

    # Получаем только известную к моменту T историю ТС.
    history = get_vehicle_history(
        traffic=traffic,
        tr_id=tr_id,
        prediction_time=prediction_time,
    )

    valid_gps = get_valid_gps(
        history
    )

    # Формируем окно телеметрии за последние 10 минут.
    window_start = (
        prediction_time
        - pd.Timedelta(
            minutes=HISTORY_WINDOW_MINUTES
        )
    )

    recent_gps = valid_gps[
        valid_gps["event_time"] >= window_start
    ].copy()

    horizon_min = (
        sample["target_time_begin"]
        - prediction_time
    ).total_seconds() / 60.0

    features = {
        "cur_dev_s": float(
            sample["cur_dev_s"]
        ),
        "horizon_min": float(
            horizon_min
        ),
        "hour": int(
            prediction_time.hour
        ),
    }

    # Признаки по последней известной GPS-точке.
    if not valid_gps.empty:
        last_point = valid_gps.iloc[-1]

        features["last_speed"] = float(
            last_point["speed"]
        )

        features["telemetry_age_s"] = float(
            (
                prediction_time
                - last_point["event_time"]
            ).total_seconds()
        )

    else:
        features["last_speed"] = float("nan")
        features["telemetry_age_s"] = float("nan")

    # Статистика движения за последние 10 минут.
    if not recent_gps.empty:
        features["mean_speed_10m"] = float(
            recent_gps["speed"].mean()
        )

        features["max_speed_10m"] = float(
            recent_gps["speed"].max()
        )

        features["stopped_share_10m"] = float(
            (
                recent_gps["speed"]
                <= STOPPED_SPEED_THRESHOLD_KMH
            ).mean()
        )

        features["gps_points_10m"] = int(
            len(recent_gps)
        )

    else:
        features["mean_speed_10m"] = float("nan")
        features["max_speed_10m"] = float("nan")
        features["stopped_share_10m"] = float("nan")
        features["gps_points_10m"] = 0

    # Находим целевую остановку в расписании.
    target_rows = schedule[
        (schedule["tr_id"] == tr_id)
        & (
            schedule["tt_action_item_id"]
            == sample["target_stop_id"]
        )
    ]

    # Расстояние считается от последней известной
    # позиции ТС до целевой остановки.
    if not target_rows.empty and not valid_gps.empty:
        target = target_rows.iloc[0]

        target_lon, target_lat = parse_point(
            target["geom"]
        )

        last_point = valid_gps.iloc[-1]

        features["distance_to_target_m"] = float(
            haversine_m(
                lon1=float(last_point["lon"]),
                lat1=float(last_point["lat"]),
                lon2=target_lon,
                lat2=target_lat,
            )
        )

    else:
        features["distance_to_target_m"] = float("nan")

    return features