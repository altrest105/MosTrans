from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_SCHEDULE_PATH = (
    PROJECT_ROOT
    / "ml"
    / "dataset"
    / "validate"
    / "schedule_plan.csv"
)

MIN_HORIZON_MINUTES = 10
MAX_HORIZON_MINUTES = 15


@dataclass(slots=True)
class StopCandidate:
    """Остановка-кандидат на целевое событие."""

    stop_id: int
    planned_time: datetime
    geom: str | None
    address: str | None

    def to_dict(self) -> dict:
        """Преобразовать кандидата в словарь."""

        return asdict(self)


@dataclass(slots=True)
class TargetWindow:
    """Результат поиска целевого события в горизонте прогноза."""

    tr_id: int
    planned_time: datetime
    horizon_min: float
    candidates: list[StopCandidate]

    @property
    def is_ambiguous(self) -> bool:
        """Проверить, найдено ли несколько остановок на одно время."""

        return len(self.candidates) > 1

    def to_dict(self) -> dict:
        """Преобразовать результат в словарь."""

        return {
            "tr_id": self.tr_id,
            "planned_time": self.planned_time,
            "horizon_min": self.horizon_min,
            "is_ambiguous": self.is_ambiguous,
            "candidates": [
                candidate.to_dict()
                for candidate in self.candidates
            ],
        }


class ScheduleService:
    """Сервис поиска остановок в прогнозном горизонте."""

    def __init__(
        self,
        schedule_path: Path = DEFAULT_SCHEDULE_PATH,
    ) -> None:
        if not schedule_path.exists():
            raise FileNotFoundError(
                f"Расписание не найдено: {schedule_path}"
            )

        schedule = pd.read_csv(
            schedule_path
        )

        schedule["time_begin"] = pd.to_datetime(
            schedule["time_begin"]
        )

        schedule = schedule.sort_values(
            [
                "tr_id",
                "time_begin",
            ],
            kind="stable",
        )

        self._schedule_by_tr = {
            int(tr_id): group.reset_index(
                drop=True
            )
            for tr_id, group in schedule.groupby(
                "tr_id"
            )
        }

    def find_target_window(
        self,
        tr_id: int,
        prediction_time: datetime | pd.Timestamp,
    ) -> TargetWindow | None:
        """
        Найти первое плановое время в окне
        (T + 10 минут, T + 15 минут].

        Если на одно время приходится несколько остановок,
        возвращаются все кандидаты.
        """

        vehicle_schedule = self._schedule_by_tr.get(
            int(tr_id)
        )

        if vehicle_schedule is None:
            return None

        prediction_time = pd.Timestamp(
            prediction_time
        )

        window_start = (
            prediction_time
            + timedelta(
                minutes=MIN_HORIZON_MINUTES
            )
        )

        window_end = (
            prediction_time
            + timedelta(
                minutes=MAX_HORIZON_MINUTES
            )
        )

        candidates = vehicle_schedule[
            (
                vehicle_schedule["time_begin"]
                > window_start
            )
            & (
                vehicle_schedule["time_begin"]
                <= window_end
            )
        ]

        if candidates.empty:
            return None

        earliest_time = candidates[
            "time_begin"
        ].min()

        earliest_rows = candidates[
            candidates["time_begin"]
            == earliest_time
        ]

        stop_candidates = []

        for _, row in earliest_rows.iterrows():
            geom = row.get(
                "geom"
            )

            address = row.get(
                "building_address"
            )

            if pd.isna(geom):
                geom = None

            if pd.isna(address):
                address = None

            stop_candidates.append(
                StopCandidate(
                    stop_id=int(
                        row["tt_action_item_id"]
                    ),
                    planned_time=pd.Timestamp(
                        row["time_begin"]
                    ).to_pydatetime(),
                    geom=geom,
                    address=address,
                )
            )

        horizon_min = (
            earliest_time
            - prediction_time
        ).total_seconds() / 60.0

        return TargetWindow(
            tr_id=int(tr_id),
            planned_time=pd.Timestamp(
                earliest_time
            ).to_pydatetime(),
            horizon_min=float(
                horizon_min
            ),
            candidates=stop_candidates,
        )

    def has_vehicle(
        self,
        tr_id: int,
    ) -> bool:
        """Проверить наличие расписания для ТС."""

        return (
            int(tr_id)
            in self._schedule_by_tr
        )

    def vehicle_count(
        self,
    ) -> int:
        """Получить количество ТС в расписании."""

        return len(
            self._schedule_by_tr
        )

    def vehicle_ids(
        self,
    ) -> list[int]:
        """Получить все tr_id из расписания."""

        return sorted(
            self._schedule_by_tr.keys()
        )