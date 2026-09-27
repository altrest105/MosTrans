from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
import logging

import pandas as pd

from backend.features.live import haversine_m, parse_point

logger = logging.getLogger(__name__)

MIN_HORIZON_MINUTES = 10
MAX_HORIZON_MINUTES = 15


@dataclass(slots=True)
class StopCandidate:
    """Плановая остановка на конкретную календарную дату."""

    stop_id: int
    planned_time: datetime
    geom: str | None
    address: str | None


@dataclass(slots=True)
class TargetWindow:
    """Плановая остановка внутри обязательного окна T+10..15 минут."""

    tr_id: int
    planned_time: datetime
    horizon_min: float
    candidates: list[StopCandidate]


@dataclass(slots=True)
class NextStopWindow:
    """Следующая остановка относительно текущего положения ТС в графике."""

    tr_id: int
    planned_time: datetime
    schedule_position_time: datetime
    candidates: list[StopCandidate]


@dataclass(slots=True)
class NearestRouteStop:
    """Ближайшая по GPS остановка, принадлежащая расписанию конкретного ТС."""

    stop: StopCandidate
    distance_m: float


class ScheduleService:
    """Суточное расписание, повторяющееся каждый календарный день.

    ``schedule_plan.csv`` хранит эталонный день. Для live-потока используется
    время суток исходной строки, а дата берётся из текущего NDTP-времени.
    """

    def __init__(self, schedule_path: Path) -> None:
        self._schedule_by_tr: dict[int, pd.DataFrame] = {}
        self._route_cache: dict[tuple[int, date], list[dict]] = {}

        if not schedule_path.exists():
            logger.warning("Расписание не найдено: %s", schedule_path)
            return

        schedule = pd.read_csv(schedule_path)
        schedule["time_begin"] = pd.to_datetime(schedule["time_begin"])
        schedule = schedule.sort_values(["tr_id", "time_begin"], kind="stable")

        self._schedule_by_tr = {
            int(tr_id): group.reset_index(drop=True)
            for tr_id, group in schedule.groupby("tr_id")
        }

        logger.info(
            "Загружено ТС с суточным расписанием: %d",
            len(self._schedule_by_tr),
        )

    @property
    def enabled(self) -> bool:
        return bool(self._schedule_by_tr)

    @staticmethod
    def _materialize(source_time: pd.Timestamp | datetime, day: date) -> datetime:
        value = pd.Timestamp(source_time).to_pydatetime()
        return datetime.combine(
            day,
            time(
                hour=value.hour,
                minute=value.minute,
                second=value.second,
                microsecond=value.microsecond,
            ),
        )

    @staticmethod
    def _row_to_stop(row: pd.Series, planned_time: datetime) -> StopCandidate:
        geom = None if pd.isna(row.get("geom")) else str(row.get("geom"))
        address = (
            None
            if pd.isna(row.get("building_address"))
            else str(row.get("building_address"))
        )

        return StopCandidate(
            stop_id=int(row["tt_action_item_id"]),
            planned_time=planned_time,
            geom=geom,
            address=address,
        )

    def _materialized_rows(
        self,
        tr_id: int,
        start_day: date,
        days: int = 2,
    ) -> list[tuple[pd.Series, datetime]]:
        rows = self._schedule_by_tr.get(int(tr_id))
        if rows is None:
            return []

        result: list[tuple[pd.Series, datetime]] = []
        for day_offset in range(days):
            day = start_day + timedelta(days=day_offset)
            for _, row in rows.iterrows():
                result.append((row, self._materialize(row["time_begin"], day)))

        result.sort(key=lambda item: item[1])
        return result

    def find_stop(
        self,
        tr_id: int,
        stop_id: int,
        planned_time: datetime | None = None,
    ) -> StopCandidate | None:
        """Найти остановку, применив её время суток к нужному дню."""

        rows = self._schedule_by_tr.get(int(tr_id))
        if rows is None:
            return None

        candidates = rows[
            rows["tt_action_item_id"].astype(int) == int(stop_id)
        ]
        if candidates.empty:
            return None

        if planned_time is None:
            row = candidates.iloc[0]
            materialized = self._materialize(row["time_begin"], datetime.now().date())
            return self._row_to_stop(row, materialized)

        expected = pd.Timestamp(planned_time).to_pydatetime()
        expected_seconds = expected.hour * 3600 + expected.minute * 60 + expected.second

        best_row = None
        best_delta = None
        for _, row in candidates.iterrows():
            source = pd.Timestamp(row["time_begin"]).to_pydatetime()
            source_seconds = source.hour * 3600 + source.minute * 60 + source.second
            delta = abs(source_seconds - expected_seconds)
            if best_delta is None or delta < best_delta:
                best_delta = delta
                best_row = row

        if best_row is None:
            return None

        return self._row_to_stop(
            best_row,
            self._materialize(best_row["time_begin"], expected.date()),
        )

    def find_target_window(
        self,
        tr_id: int,
        prediction_time: datetime,
    ) -> TargetWindow | None:
        """Найти первое плановое событие в (T+10, T+15]."""

        prediction_time = pd.Timestamp(prediction_time).to_pydatetime().replace(tzinfo=None)
        window_start = prediction_time + timedelta(minutes=MIN_HORIZON_MINUTES)
        window_end = prediction_time + timedelta(minutes=MAX_HORIZON_MINUTES)

        candidates = [
            (row, planned)
            for row, planned in self._materialized_rows(
                tr_id,
                prediction_time.date(),
                days=2,
            )
            if planned > window_start and planned <= window_end
        ]
        if not candidates:
            return None

        earliest_time = min(planned for _, planned in candidates)
        earliest_rows = [
            (row, planned)
            for row, planned in candidates
            if planned == earliest_time
        ]

        stops = [self._row_to_stop(row, planned) for row, planned in earliest_rows]

        return TargetWindow(
            tr_id=int(tr_id),
            planned_time=earliest_time,
            horizon_min=float((earliest_time - prediction_time).total_seconds() / 60.0),
            candidates=stops,
        )

    def find_target_near_horizon(
        self,
        tr_id: int,
        prediction_time: datetime,
        horizon_min: float,
    ) -> TargetWindow | None:
        """Найти остановку внутри (T+10, T+15], ближайшую к T+horizon.

        Runtime использует фиксированный ML-горизонт 12.5 минуты. Если в
        расписании нет остановки ровно через 12.5 минуты, выбирается ближайшая
        плановая остановка внутри обязательного окна 10–15 минут.
        """

        prediction_time = pd.Timestamp(prediction_time).to_pydatetime().replace(tzinfo=None)
        desired_time = prediction_time + timedelta(minutes=float(horizon_min))
        window_start = prediction_time + timedelta(minutes=MIN_HORIZON_MINUTES)
        window_end = prediction_time + timedelta(minutes=MAX_HORIZON_MINUTES)

        candidates = [
            (row, planned)
            for row, planned in self._materialized_rows(
                tr_id,
                prediction_time.date(),
                days=2,
            )
            if planned > window_start and planned <= window_end
        ]
        if not candidates:
            return None

        best_time = min(
            (planned for _, planned in candidates),
            key=lambda planned: abs((planned - desired_time).total_seconds()),
        )
        best_rows = [
            (row, planned)
            for row, planned in candidates
            if planned == best_time
        ]

        return TargetWindow(
            tr_id=int(tr_id),
            planned_time=best_time,
            horizon_min=float((best_time - prediction_time).total_seconds() / 60.0),
            candidates=[
                self._row_to_stop(row, planned)
                for row, planned in best_rows
            ],
        )

    def service_status(
        self,
        tr_id: int,
        current_time: datetime,
    ) -> dict:
        """Определить, идёт ли ТС сейчас по суточному расписанию.

        Статус считается только по текущему календарному дню. Мы намеренно
        не считаем первую остановку следующего дня "следующей" для уже
        завершившего работу ТС. Это особенно важно для live-эмулятора,
        который может продолжать присылать координаты после конца графика.
        """

        current_time = pd.Timestamp(current_time).to_pydatetime().replace(tzinfo=None)
        rows = self._schedule_by_tr.get(int(tr_id))
        if rows is None or rows.empty:
            return {
                "status": "schedule_missing",
                "text": "Расписание не найдено",
                "first_planned_time": None,
                "last_planned_time": None,
            }

        planned_times = [
            self._materialize(value, current_time.date())
            for value in rows["time_begin"]
        ]
        first_planned = min(planned_times)
        last_planned = max(planned_times)

        if current_time < first_planned:
            status = "not_started"
            text = "Рейс ещё не начался"
        elif current_time > last_planned:
            status = "finished"
            text = "Рейс завершён"
        else:
            status = "active"
            text = "На маршруте"

        return {
            "status": status,
            "text": text,
            "first_planned_time": first_planned,
            "last_planned_time": last_planned,
        }

    def find_next_stop_window(
        self,
        tr_id: int,
        current_time: datetime,
        current_deviation_s: float | None = None,
    ) -> NextStopWindow | None:
        """Найти следующую остановку по текущему положению ТС в расписании.

        Если известно текущее отклонение, сначала восстанавливаем условное
        положение ТС на временной оси расписания: ``T - cur_dev_s``.
        Поэтому для опаздывающего автобуса следующей может оставаться остановка,
        чьё плановое время уже немного прошло по настенным часам.
        """

        current_time = pd.Timestamp(current_time).to_pydatetime().replace(tzinfo=None)
        deviation_s = 0.0 if current_deviation_s is None else float(current_deviation_s)
        schedule_position_time = current_time - timedelta(seconds=deviation_s)

        # Для карточки оператора следующая остановка относится только к
        # текущему суточному графику. После последней остановки дня не
        # перепрыгиваем на первый рейс следующего дня.
        candidates = [
            (row, planned)
            for row, planned in self._materialized_rows(
                tr_id,
                schedule_position_time.date(),
                days=1,
            )
            if planned > schedule_position_time
        ]
        if not candidates:
            return None

        earliest_time = min(planned for _, planned in candidates)
        earliest_rows = [
            (row, planned)
            for row, planned in candidates
            if planned == earliest_time
        ]

        return NextStopWindow(
            tr_id=int(tr_id),
            planned_time=earliest_time,
            schedule_position_time=schedule_position_time,
            candidates=[
                self._row_to_stop(row, planned)
                for row, planned in earliest_rows
            ],
        )


    def find_nearest_route_stop(
        self,
        tr_id: int,
        current_time: datetime,
        lon: float,
        lat: float,
    ) -> NearestRouteStop | None:
        """Найти ближайшую по GPS остановку, принадлежащую этому ``tr_id``.

        Это fallback для realtime-режима. Он нужен, когда временное
        сопоставление с расписанием не смогло определить следующую остановку.
        Остановки других ТС никогда не рассматриваются. Если одна и та же
        географическая точка встречается в расписании несколько раз, берётся
        ближайшее будущее плановое прохождение этой точки.
        """

        current_time = pd.Timestamp(current_time).to_pydatetime().replace(tzinfo=None)
        rows = self._schedule_by_tr.get(int(tr_id))
        if rows is None or rows.empty:
            return None

        best: tuple[float, float, StopCandidate] | None = None

        for _, row in rows.iterrows():
            geom = None if pd.isna(row.get("geom")) else str(row.get("geom"))
            point = parse_point(geom)
            if point is None:
                continue

            stop_lon, stop_lat = point
            distance_m = haversine_m(
                float(lon),
                float(lat),
                float(stop_lon),
                float(stop_lat),
            )

            planned = self._materialize(row["time_begin"], current_time.date())
            if planned <= current_time:
                planned += timedelta(days=1)

            seconds_until = (planned - current_time).total_seconds()
            stop = self._row_to_stop(row, planned)
            candidate = (float(distance_m), float(seconds_until), stop)

            if best is None or candidate[:2] < best[:2]:
                best = candidate

        if best is None:
            return None

        return NearestRouteStop(stop=best[2], distance_m=best[0])

    def route_for_day(self, tr_id: int, day: date) -> list[dict]:
        """Получить суточный маршрут, разделённый на рейсы по длинным паузам."""

        cache_key = (int(tr_id), day)
        cached = self._route_cache.get(cache_key)
        if cached is not None:
            return [dict(item) for item in cached]

        rows = self._schedule_by_tr.get(int(tr_id))
        if rows is None:
            return []

        result: list[dict] = []
        segment_id = 0
        previous_time: datetime | None = None

        for _, row in rows.iterrows():
            geom = None if pd.isna(row.get("geom")) else str(row.get("geom"))
            point = parse_point(geom)
            if point is None:
                continue

            lon, lat = point
            planned_time = self._materialize(row["time_begin"], day)

            # Не соединяем разные рейсы одной длинной прямой.
            if (
                previous_time is not None
                and (planned_time - previous_time).total_seconds() > 10 * 60
            ):
                segment_id += 1

            result.append(
                {
                    "stop_id": int(row["tt_action_item_id"]),
                    "planned_time": planned_time,
                    "lon": float(lon),
                    "lat": float(lat),
                    "segment_id": segment_id,
                    "address": (
                        None
                        if pd.isna(row.get("building_address"))
                        else str(row.get("building_address"))
                    ),
                }
            )
            previous_time = planned_time

        self._route_cache[cache_key] = [dict(item) for item in result]
        return result

    def estimate_current_deviation(
        self,
        tr_id: int,
        current_time: datetime,
        lon: float,
        lat: float,
        search_minutes: int = 15,
        max_distance_m: float = 200.0,
    ) -> float | None:
        """Оценить текущее отклонение по ближайшей плановой остановке.

        Возвращается знаковое отклонение: ``+`` означает опоздание, ``-`` —
        опережение. Значение считается только когда live GPS действительно
        находится рядом с плановой остановкой около текущего времени.
        """

        current_time = pd.Timestamp(current_time).to_pydatetime().replace(tzinfo=None)
        start = current_time - timedelta(minutes=search_minutes)
        end = current_time + timedelta(minutes=search_minutes)

        best: tuple[float, datetime] | None = None
        for row, planned in self._materialized_rows(tr_id, current_time.date(), days=2):
            if planned < start or planned > end:
                continue

            geom = None if pd.isna(row.get("geom")) else str(row.get("geom"))
            point = parse_point(geom)
            if point is None:
                continue

            stop_lon, stop_lat = point
            distance = haversine_m(float(lon), float(lat), stop_lon, stop_lat)
            if distance > max_distance_m:
                continue

            if best is None or distance < best[0]:
                best = (distance, planned)

        if best is None:
            return None

        return float((current_time - best[1]).total_seconds())
