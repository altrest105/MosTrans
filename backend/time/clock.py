from dataclasses import replace
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from backend.ndtp.parser import TelemetryEvent


class ScheduleClock:
    """Приводит NDTP timestamp к московскому времени расписания.

    Расписание считается суточным шаблоном, одинаковым для каждого дня.
    Поэтому дата NDTP не подменяется: меняется только timezone UTC -> Europe/Moscow,
    а schedule_plan применяется к текущей календарной дате по времени суток.
    """

    def __init__(self, local_timezone: str = "Europe/Moscow") -> None:
        self._local_tz = ZoneInfo(local_timezone)
        self._last_source_time: datetime | None = None
        self._last_schedule_time: datetime | None = None

    @property
    def initialized(self) -> bool:
        return self._last_source_time is not None

    def map_datetime(self, source_time: datetime) -> datetime:
        """Перевести UTC timestamp NDTP в локальное время расписания без tzinfo."""

        if source_time.tzinfo is None:
            source_time = source_time.replace(tzinfo=timezone.utc)
        else:
            source_time = source_time.astimezone(timezone.utc)

        local_time = source_time.astimezone(self._local_tz).replace(tzinfo=None)
        self._last_source_time = source_time
        self._last_schedule_time = local_time
        return local_time

    def map_event(self, event: TelemetryEvent) -> TelemetryEvent:
        """Вернуть копию события в локальной временной шкале расписания."""

        source_time = event.event_time
        schedule_time = self.map_datetime(source_time)

        return replace(
            event,
            event_time=schedule_time,
            source_event_time=source_time,
        )

    def status(self) -> dict:
        return {
            "initialized": self.initialized,
            "mode": "daily_schedule_template",
            "timezone": str(self._local_tz),
            "source_time": self._last_source_time,
            "schedule_time": self._last_schedule_time,
            "description": (
                "schedule_plan.csv используется как повторяющийся суточный шаблон; "
                "текущая дата берётся из NDTP, время переводится в Europe/Moscow."
            ),
        }
