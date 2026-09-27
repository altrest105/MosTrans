from datetime import datetime, timedelta, timezone
from math import asin, cos, radians, sin, sqrt

from backend.ndtp.parser import TelemetryEvent

EARTH_RADIUS_M = 6_371_000.0
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


def normalize_datetime(value: datetime) -> datetime:
    """Привести datetime к UTC без timezone для совместимой арифметики."""

    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def parse_point(value: str | None) -> tuple[float, float] | None:
    """Разобрать WKT POINT в lon, lat."""

    if not value:
        return None

    value = value.strip()
    if not value.startswith("POINT"):
        return None

    try:
        parts = value.removeprefix("POINT").strip().strip("()").split()
        return float(parts[0]), float(parts[1])
    except (ValueError, IndexError):
        return None


def haversine_m(
    lon1: float,
    lat1: float,
    lon2: float,
    lat2: float,
) -> float:
    """Расстояние между двумя GPS-точками в метрах."""

    lon1_rad = radians(lon1)
    lat1_rad = radians(lat1)
    lon2_rad = radians(lon2)
    lat2_rad = radians(lat2)

    delta_lon = lon2_rad - lon1_rad
    delta_lat = lat2_rad - lat1_rad

    a = (
        sin(delta_lat / 2.0) ** 2
        + cos(lat1_rad)
        * cos(lat2_rad)
        * sin(delta_lon / 2.0) ** 2
    )

    return 2.0 * EARTH_RADIUS_M * asin(sqrt(a))


def calculate_dwell_time_s(
    history: list[TelemetryEvent],
    prediction_time: datetime,
    window_minutes: int = HISTORY_WINDOW_MINUTES,
) -> float:
    """Оценить время простоя по соседним валидным NDTP-наблюдениям.

    Для каждого интервала между соседними GPS-пакетами учитывается время,
    если скорость в начале интервала была не выше 1 км/ч. Интервалы
    обрезаются границами последних ``window_minutes`` минут. Будущие пакеты
    относительно ``prediction_time`` не используются.
    """

    prediction_time = normalize_datetime(prediction_time)
    window_start = prediction_time - timedelta(minutes=window_minutes)

    valid = [
        event
        for event in history
        if event.location_valid
        and normalize_datetime(event.event_time) <= prediction_time
    ]
    valid.sort(key=lambda event: normalize_datetime(event.event_time))

    if len(valid) < 2:
        return 0.0

    stopped_time_s = 0.0

    for current, following in zip(valid, valid[1:]):
        current_time = normalize_datetime(current.event_time)
        following_time = normalize_datetime(following.event_time)

        interval_start = max(current_time, window_start)
        interval_end = min(following_time, prediction_time)

        if interval_end <= interval_start:
            continue

        if float(current.speed) <= STOPPED_SPEED_THRESHOLD_KMH:
            stopped_time_s += (interval_end - interval_start).total_seconds()

    return max(0.0, stopped_time_s)


class LiveFeatureBuilder:
    """Построение тех же 10 признаков CatBoost из live NDTP-состояния."""

    def build(
        self,
        history: list[TelemetryEvent],
        prediction_time: datetime,
        horizon_min: float,
        cur_dev_s: float | None = None,
        target_geom: str | None = None,
    ) -> dict[str, float | None]:
        prediction_time = normalize_datetime(prediction_time)

        history = [
            event
            for event in history
            if normalize_datetime(event.event_time) <= prediction_time
        ]
        history.sort(key=lambda event: normalize_datetime(event.event_time))

        features: dict[str, float | None] = {
            "cur_dev_s": None if cur_dev_s is None else float(cur_dev_s),
            "horizon_min": float(horizon_min),
            "hour": float(prediction_time.hour),
            "last_speed": None,
            "telemetry_age_s": None,
            "mean_speed_10m": None,
            "max_speed_10m": None,
            "stopped_share_10m": None,
            "gps_points_10m": 0.0,
            "distance_to_target_m": None,
        }

        if not history:
            return features

        valid_history = [event for event in history if event.location_valid]

        if valid_history:
            last_valid = valid_history[-1]
            features["last_speed"] = float(last_valid.speed)
            features["telemetry_age_s"] = max(
                0.0,
                (
                    prediction_time
                    - normalize_datetime(last_valid.event_time)
                ).total_seconds(),
            )

        window_start = prediction_time - timedelta(
            minutes=HISTORY_WINDOW_MINUTES
        )
        recent_valid = [
            event
            for event in valid_history
            if normalize_datetime(event.event_time) >= window_start
        ]

        if recent_valid:
            speeds = [float(event.speed) for event in recent_valid]
            features["mean_speed_10m"] = sum(speeds) / len(speeds)
            features["max_speed_10m"] = max(speeds)
            features["stopped_share_10m"] = (
                sum(speed <= STOPPED_SPEED_THRESHOLD_KMH for speed in speeds)
                / len(speeds)
            )
            features["gps_points_10m"] = float(len(recent_valid))

        target_point = parse_point(target_geom)
        if valid_history and target_point is not None:
            last_valid = valid_history[-1]
            target_lon, target_lat = target_point
            features["distance_to_target_m"] = haversine_m(
                lon1=float(last_valid.lon),
                lat1=float(last_valid.lat),
                lon2=target_lon,
                lat2=target_lat,
            )

        return features

    def operational_metrics(
        self,
        history: list[TelemetryEvent],
        prediction_time: datetime,
    ) -> dict[str, float | None]:
        """Рассчитать показатели Backend, не меняя набор ML-признаков."""

        prediction_time = normalize_datetime(prediction_time)
        recent = [
            event
            for event in history
            if event.location_valid
            and normalize_datetime(event.event_time) <= prediction_time
            and normalize_datetime(event.event_time)
            >= prediction_time - timedelta(minutes=HISTORY_WINDOW_MINUTES)
        ]

        speeds = [float(event.speed) for event in recent]

        return {
            "average_speed_kmh": (
                sum(speeds) / len(speeds)
                if speeds
                else None
            ),
            "dwell_time_s": calculate_dwell_time_s(
                history=history,
                prediction_time=prediction_time,
            ),
            "gps_points_10m": float(len(recent)),
        }
