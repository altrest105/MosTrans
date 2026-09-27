from collections import defaultdict, deque
from copy import deepcopy
from math import isfinite


TRAIL_HISTORY_LIMIT = 10_000


class PredictionStore:
    """Последний прогноз и история движения/риска по каждому unit_id."""

    def __init__(self, trail_history_limit: int = TRAIL_HISTORY_LIMIT) -> None:
        self._items: dict[int, dict] = {}
        self._trails: dict[int, deque[dict]] = defaultdict(
            lambda: deque(maxlen=trail_history_limit)
        )

    def set(self, unit_id: int, prediction: dict) -> None:
        """Сохранить последнее состояние и новую точку цветной траектории.

        Точка добавляется только для нового prediction_time. Поэтому повторное
        сохранение того же прогноза при stale/degraded не дублирует маршрут.
        """

        unit_id = int(unit_id)
        item = deepcopy(prediction)
        self._items[unit_id] = item
        self._append_trail_point(unit_id, item)

    def get(self, unit_id: int) -> dict | None:
        item = self._items.get(int(unit_id))
        return None if item is None else deepcopy(item)

    def all(self) -> list[dict]:
        return [deepcopy(self._items[key]) for key in sorted(self._items)]

    def get_trail(self, unit_id: int) -> list[dict]:
        """Получить накопленную траекторию ТС за текущую сессию Backend."""

        return [deepcopy(point) for point in self._trails.get(int(unit_id), ())]

    def all_trails(self) -> list[dict]:
        """Получить цветную историю движения всех ТС."""

        result = []
        for unit_id in sorted(self._trails):
            result.append(
                {
                    "unit_id": unit_id,
                    "points": self.get_trail(unit_id),
                }
            )
        return result

    def _append_trail_point(self, unit_id: int, item: dict) -> None:
        event_time = item.get("prediction_time")
        lat = item.get("lat")
        lon = item.get("lon")

        if event_time is None or lat is None or lon is None:
            return

        try:
            lat_value = float(lat)
            lon_value = float(lon)
        except (TypeError, ValueError):
            return

        if not isfinite(lat_value) or not isfinite(lon_value):
            return

        trail = self._trails[unit_id]

        # stale/degraded обновляет существующий prediction с тем же T.
        # Такие записи не должны создавать ложное движение на карте.
        if trail and trail[-1].get("event_time") == event_time:
            return

        trail.append(
            {
                "event_time": event_time,
                "lon": lon_value,
                "lat": lat_value,
                "risk": item.get("risk", "green"),
                "status": item.get("status", "ok"),
                "deviation_s": item.get(
                    "deviation_s",
                    item.get("prediction_s"),
                ),
                "speed": item.get("speed"),
            }
        )
