from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from backend.ndtp.parser import TelemetryEvent


HISTORY_RETENTION_MINUTES = 15


class TelemetryStore:
    """Хранилище последних телематических данных по ТС."""

    def __init__(
        self,
        retention_minutes: int = HISTORY_RETENTION_MINUTES,
    ) -> None:
        self.retention = timedelta(
            minutes=retention_minutes
        )

        self._history: dict[
            int,
            deque[TelemetryEvent],
        ] = defaultdict(deque)

    def add(
        self,
        event: TelemetryEvent,
    ) -> None:
        """Добавить телематическое событие и удалить устаревшую историю."""

        history = self._history[
            event.unit_id
        ]

        history.append(
            event
        )

        cutoff = (
            event.event_time
            - self.retention
        )

        while (
            history
            and history[0].event_time < cutoff
        ):
            history.popleft()

    def get_history(
        self,
        unit_id: int,
    ) -> list[TelemetryEvent]:
        """Получить сохранённую историю одного ТС."""

        return list(
            self._history.get(
                unit_id,
                (),
            )
        )

    def get_latest(
        self,
        unit_id: int,
    ) -> TelemetryEvent | None:
        """Получить последнюю известную телеметрию ТС."""

        history = self._history.get(
            unit_id
        )

        if not history:
            return None

        return history[-1]

    def get_vehicle_ids(
        self,
    ) -> list[int]:
        """Получить список известных unit_id."""

        return sorted(
            self._history.keys()
        )

    def get_vehicle_summaries(
        self,
    ) -> list[dict]:
        """Получить текущее состояние всех известных ТС."""

        now = datetime.now(
            timezone.utc
        )

        vehicles = []

        for unit_id in self.get_vehicle_ids():
            latest = self.get_latest(
                unit_id
            )

            if latest is None:
                continue

            telemetry_age_s = max(
                0.0,
                (
                    now
                    - latest.event_time
                ).total_seconds(),
            )

            vehicles.append(
                {
                    "unit_id": unit_id,
                    "event_time": latest.event_time,
                    "lat": latest.lat,
                    "lon": latest.lon,
                    "speed": latest.speed,
                    "heading": latest.heading,
                    "location_valid": latest.location_valid,
                    "telemetry_age_s": telemetry_age_s,
                    "history_size": len(
                        self._history[unit_id]
                    ),
                }
            )

        return vehicles