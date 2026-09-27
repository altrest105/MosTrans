from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from backend.ndtp.parser import TelemetryEvent


class TelemetryStore:
    """In-memory история NDTP-телеметрии по unit_id."""

    def __init__(self, retention_minutes: int = 15) -> None:
        self._retention = timedelta(minutes=retention_minutes)
        self._history: dict[int, deque[TelemetryEvent]] = defaultdict(deque)
        self._last_received_at: dict[int, datetime] = {}

    def add(self, event: TelemetryEvent) -> None:
        """Добавить событие и удалить устаревшую live-историю."""

        history = self._history[event.unit_id]
        history.append(event)
        self._last_received_at[event.unit_id] = datetime.now(timezone.utc)

        cutoff = event.event_time - self._retention
        while history and history[0].event_time < cutoff:
            history.popleft()

    def get_history(self, unit_id: int) -> list[TelemetryEvent]:
        return list(self._history.get(int(unit_id), ()))

    def get_history_since(
        self,
        unit_id: int,
        since: datetime,
    ) -> list[TelemetryEvent]:
        return [
            event
            for event in self.get_history(unit_id)
            if event.event_time >= since
        ]

    def get_latest(self, unit_id: int) -> TelemetryEvent | None:
        history = self._history.get(int(unit_id))
        if not history:
            return None
        return history[-1]

    def get_vehicle_ids(self) -> list[int]:
        return sorted(self._history.keys())

    def get_telemetry_age_s(self, unit_id: int) -> float | None:
        """Возраст телеметрии по времени фактического приёма NDTP."""

        received_at = self._last_received_at.get(int(unit_id))
        if received_at is None:
            return None

        return max(
            0.0,
            (datetime.now(timezone.utc) - received_at).total_seconds(),
        )

    def get_vehicle_summaries(self) -> list[dict]:
        result = []

        for unit_id in self.get_vehicle_ids():
            latest = self.get_latest(unit_id)
            if latest is None:
                continue

            result.append(
                {
                    "unit_id": unit_id,
                    # event_time приведён к московскому времени суточного расписания.
                    "event_time": latest.event_time,
                    # Исходное время, пришедшее в NDTP Nav00.
                    "source_event_time": latest.source_event_time,
                    "lat": latest.lat,
                    "lon": latest.lon,
                    "speed": latest.speed,
                    "heading": latest.heading,
                    "location_valid": latest.location_valid,
                    "telemetry_age_s": self.get_telemetry_age_s(unit_id),
                    "history_size": len(self._history[unit_id]),
                }
            )

        return result
