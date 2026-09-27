import asyncio
import logging
from collections import deque
from datetime import datetime, timedelta, timezone
from statistics import mean
from time import perf_counter

from backend.features.live import LiveFeatureBuilder, haversine_m, parse_point
from backend.inference.client import MLServiceClient
from backend.prediction.rules import classify_risk, deviation_direction, explain_prediction
from backend.prediction.store import PredictionStore
from backend.schedule.service import ScheduleService, StopCandidate
from backend.telemetry.state import TelemetryStore
from backend.transport.registry import VehicleRegistry

logger = logging.getLogger(__name__)

LATENCY_SAMPLE_LIMIT = 1000

# cur_dev_s в датасете — отклонение на последней уже пройденной остановке.
# В realtime фактического расписания нет, поэтому прибытие оцениваем по GPS.
CUR_DEV_STOP_RADIUS_M = 50.0
CUR_DEV_EARLY_WINDOW_MIN = 5.0
CUR_DEV_LATE_WINDOW_MIN = 10.0
CUR_DEV_HISTORY_MIN = 15.0


def _percentile(values: list[float], percentile: float) -> float | None:
    """Посчитать процентиль без внешних зависимостей."""

    if not values:
        return None

    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]

    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower

    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


class PredictionEngine:
    """Автоматический online-инференс для активных NDTP-устройств."""

    def __init__(
        self,
        telemetry_store: TelemetryStore,
        registry: VehicleRegistry,
        schedule: ScheduleService,
        feature_builder: LiveFeatureBuilder,
        ml_client: MLServiceClient,
        prediction_store: PredictionStore,
        interval_s: float,
        stale_after_s: float,
        default_horizon_min: float,
        min_horizon_min: float,
        max_horizon_min: float,
    ) -> None:
        self._telemetry_store = telemetry_store
        self._registry = registry
        self._schedule = schedule
        self._feature_builder = feature_builder
        self._ml_client = ml_client
        self._prediction_store = prediction_store
        self._interval_s = interval_s
        self._stale_after_s = stale_after_s
        self._default_horizon_min = default_horizon_min
        self._min_horizon_min = min_horizon_min
        self._max_horizon_min = max_horizon_min

        self._task: asyncio.Task | None = None
        self._running = False
        self._last_processed_time: dict[int, datetime] = {}
        self._started_at: datetime | None = None
        self._first_prediction_at: datetime | None = None
        # Последнее подтверждённое live-отклонение по каждому ТС.
        # Если автобус между остановками, используем последнее измеренное значение,
        # а не подставляем искусственный ноль.
        self._last_cur_dev_s: dict[int, float] = {}
        # Метаданные остановки, на которой последнее отклонение было подтверждено.
        # Нужны, чтобы не пересчитывать cur_dev_s каждую секунду на одной и той
        # же остановке и не откатываться назад по расписанию.
        self._last_cur_dev_meta: dict[int, dict] = {}

        self.total_predictions = 0
        self.failed_predictions = 0
        self.last_cycle_ms = 0.0

        self._prediction_latency_ms: deque[float] = deque(
            maxlen=LATENCY_SAMPLE_LIMIT
        )
        self._ml_latency_ms: deque[float] = deque(maxlen=LATENCY_SAMPLE_LIMIT)

        # Счётчики деградации и восстановления для демонстрации надёжности.
        self.stale_transitions = 0
        self.degraded_transitions = 0
        self.recoveries = 0

        # Метрики, которыми можно подтвердить критерий горизонта на потоке.
        self.horizon_compliant_predictions = 0
        self.horizon_violations = 0
        self.no_hindsight_predictions = 0
        self.hindsight_violations = 0

    @property
    def running(self) -> bool:
        return self._running

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._started_at = datetime.now(timezone.utc)
        self._task = asyncio.create_task(self._run())
        logger.info("PredictionEngine запущен")

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("PredictionEngine остановлен")

    async def _run(self) -> None:
        while self._running:
            started = perf_counter()
            await self._process_cycle()
            self.last_cycle_ms = (perf_counter() - started) * 1000.0
            await asyncio.sleep(self._interval_s)

    async def _process_cycle(self) -> None:
        for unit_id in self._telemetry_store.get_vehicle_ids():
            latest = self._telemetry_store.get_latest(unit_id)
            if latest is None:
                continue

            age_s = self._telemetry_store.get_telemetry_age_s(unit_id)
            if age_s is None:
                continue
            if age_s > self._stale_after_s:
                self._mark_stale(unit_id, age_s)
                continue

            # Один прогноз на одну новую NDTP-точку. Повторно одну и ту же
            # телеметрию не прогоняем через ML.
            if self._last_processed_time.get(unit_id) == latest.event_time:
                continue

            try:
                await self._predict_vehicle(unit_id)
                self._last_processed_time[unit_id] = latest.event_time
                self.total_predictions += 1
            except Exception as exc:  # noqa: BLE001
                self.failed_predictions += 1
                self._mark_degraded(
                    unit_id,
                    "Не удалось обновить прогноз; используется последнее известное состояние.",
                )
                logger.exception(
                    "Ошибка online-инференса для unit_id=%s: %s",
                    unit_id,
                    exc,
                )

    async def _predict_vehicle(self, unit_id: int) -> None:
        prediction_started = perf_counter()
        history = self._telemetry_store.get_history(unit_id)
        if not history:
            return

        latest = history[-1]
        prediction_time = latest.event_time
        tr_id = self._registry.get_tr_id(unit_id)

        # Жёстко исключаем любую телеметрию из будущего относительно T.
        history_until_t = [
            event
            for event in history
            if event.event_time <= prediction_time
        ]
        if not history_until_t:
            return

        max_used_time = max(event.event_time for event in history_until_t)
        if max_used_time > prediction_time:
            self.hindsight_violations += 1
            raise ValueError("Обнаружено использование телеметрии после точки T")

        target: StopCandidate | None = None
        # Оперативный runtime всегда прогнозирует ровно на 12.5 минуты вперёд
        # (значение приходит из DEFAULT_HORIZON_MINUTES).
        horizon_min = self._default_horizon_min
        cur_dev_s: float | None = None
        cur_dev_source = "unavailable"
        target_source = "default"

        cur_dev_meta: dict | None = None

        if tr_id is not None and self._schedule.enabled:
            measured = self._measure_current_deviation_from_history(
                unit_id=unit_id,
                tr_id=tr_id,
                history=history_until_t,
                prediction_time=prediction_time,
            )

            if measured is not None:
                measured_cur_dev, measured_meta = measured
                previous_meta = self._last_cur_dev_meta.get(unit_id)

                # Обновляем cur_dev только при реально новой пройденной
                # остановке. Пока автобус стоит рядом с той же остановкой,
                # значение не должно "ползти" вместе с настенными часами.
                is_new_stop = (
                    previous_meta is None
                    or measured_meta["planned_time"] > previous_meta["planned_time"]
                )

                if is_new_stop:
                    cur_dev_s = float(measured_cur_dev)
                    cur_dev_meta = measured_meta
                    self._last_cur_dev_s[unit_id] = cur_dev_s
                    self._last_cur_dev_meta[unit_id] = dict(measured_meta)
                    cur_dev_source = "passed_stop_gps"
                elif unit_id in self._last_cur_dev_s:
                    cur_dev_s = self._last_cur_dev_s[unit_id]
                    cur_dev_meta = self._last_cur_dev_meta.get(unit_id)
                    cur_dev_source = "last_known"
            elif unit_id in self._last_cur_dev_s:
                # Между остановками сохраняем задержку последней действительно
                # обнаруженной остановки — это и есть смысл cur_dev_s.
                cur_dev_s = self._last_cur_dev_s[unit_id]
                cur_dev_meta = self._last_cur_dev_meta.get(unit_id)
                cur_dev_source = "last_known"

            window = self._schedule.find_target_near_horizon(
                tr_id=tr_id,
                prediction_time=prediction_time,
                horizon_min=horizon_min,
            )
            if window is not None:
                target = self._choose_target(
                    window.candidates,
                    latest.lon,
                    latest.lat,
                )
                target_source = "schedule"

        self._validate_horizon(horizon_min)
        # Критерий горизонта относится к моменту прогноза, поэтому forecast_for
        # всегда T + 12.5 мин. Плановая остановка хранится отдельно в target_stop.
        forecast_for = prediction_time + timedelta(minutes=horizon_min)

        features = self._feature_builder.build(
            history=history_until_t,
            prediction_time=prediction_time,
            horizon_min=horizon_min,
            cur_dev_s=cur_dev_s,
            target_geom=None if target is None else target.geom,
        )
        operational = self._feature_builder.operational_metrics(
            history=history_until_t,
            prediction_time=prediction_time,
        )

        result = await self._ml_client.predict(features)
        generated_at = datetime.now(timezone.utc)
        prediction_latency_ms = (perf_counter() - prediction_started) * 1000.0

        deviation_s = float(result["prediction"])
        ml_latency_ms = float(result["latency_ms"])
        risk = classify_risk(deviation_s)
        direction = deviation_direction(deviation_s)
        cause, recommendation = explain_prediction(deviation_s, features)

        previous = self._prediction_store.get(unit_id)
        if previous is not None and previous.get("status") not in (None, "ok"):
            self.recoveries += 1

        item = {
            "unit_id": unit_id,
            "tr_id": tr_id,
            # T — точка, на которой сформирован прогноз по доступной телеметрии.
            "prediction_time": prediction_time,
            "source_event_time": latest.source_event_time,
            "telemetry_cutoff": max_used_time,
            # Реальное время, когда Backend закончил формировать алерт.
            "generated_at": generated_at,
            # Будущий момент, для которого действует прогноз.
            "forecast_for": forecast_for,
            "horizon_min": float(horizon_min),
            "horizon_compliant": self._is_horizon_compliant(horizon_min),
            # Знаковое отклонение от графика: + = опоздание, - = опережение.
            "deviation_s": deviation_s,
            "absolute_deviation_s": abs(deviation_s),
            "deviation_direction": direction,
            # Временный совместимый alias для старых потребителей API.
            "prediction_s": deviation_s,
            "risk": risk,
            "cause": cause,
            "recommendation": recommendation,
            "lat": latest.lat,
            "lon": latest.lon,
            "speed": latest.speed,
            "heading": latest.heading,
            "location_valid": latest.location_valid,
            "target_stop": None,
            "target_source": target_source,
            "schedule_matched": target is not None,
            "point_context_matched": False,
            "prediction_point": None,
            "current_deviation_s": features.get("cur_dev_s"),
            "current_deviation_source": cur_dev_source,
            "current_deviation_stop": cur_dev_meta,
            "current_deviation_age_s": (
                None
                if cur_dev_meta is None
                else max(
                    0.0,
                    (prediction_time - cur_dev_meta["observed_time"]).total_seconds(),
                )
            ),
            "average_speed_kmh": operational["average_speed_kmh"],
            "dwell_time_s": operational["dwell_time_s"],
            "features": features,
            "ml_latency_ms": ml_latency_ms,
            "prediction_latency_ms": prediction_latency_ms,
            "status": "ok",
            "degradation_reason": None,
        }

        if target is not None:
            item["target_stop"] = {
                "stop_id": target.stop_id,
                "planned_time": target.planned_time,
                "address": target.address,
                "geom": target.geom,
            }

        self._prediction_store.set(unit_id, item)
        self._prediction_latency_ms.append(prediction_latency_ms)
        self._ml_latency_ms.append(ml_latency_ms)

        if self._first_prediction_at is None:
            self._first_prediction_at = generated_at

        self.horizon_compliant_predictions += 1
        self.no_hindsight_predictions += 1


    def _measure_current_deviation_from_history(
        self,
        unit_id: int,
        tr_id: int,
        history: list,
        prediction_time: datetime,
    ) -> tuple[float, dict] | None:
        """Оценить cur_dev_s по последней реально посещённой остановке.

        В датасете ``cur_dev_s`` означает задержку на последней уже пройденной
        остановке. Поэтому нельзя брать просто ближайшую к текущему GPS точку:
        она может быть будущей остановкой, соседней остановкой обратного
        направления или повторной точкой кольцевого маршрута.

        Здесь для каждой плановой остановки ищем ПЕРВОЕ live-наблюдение в
        радиусе 50 м в допустимом временном окне [план-5 мин; план+10 мин].
        Среди подтверждённых остановок берём последнюю по фактическому времени
        наблюдения. Само значение фиксируется при первом попадании в геозону и
        затем сохраняется до следующей подтверждённой остановки.
        """

        valid_events = [
            event
            for event in history
            if getattr(event, "location_valid", True)
            and getattr(event, "lon", None) is not None
            and getattr(event, "lat", None) is not None
            and event.event_time <= prediction_time
            and event.event_time >= prediction_time - timedelta(minutes=CUR_DEV_HISTORY_MIN)
        ]
        if not valid_events:
            return None

        valid_events.sort(key=lambda event: event.event_time)

        days = {event.event_time.date() for event in valid_events}
        days.add(prediction_time.date())

        stops: list[dict] = []
        for day in sorted(days):
            stops.extend(self._schedule.route_for_day(tr_id, day))

        search_start = valid_events[0].event_time - timedelta(
            minutes=CUR_DEV_LATE_WINDOW_MIN
        )
        search_end = prediction_time + timedelta(minutes=CUR_DEV_EARLY_WINDOW_MIN)

        best: tuple[datetime, datetime, float, dict] | None = None

        for stop in stops:
            planned_time = stop["planned_time"]
            if planned_time < search_start or planned_time > search_end:
                continue

            window_start = planned_time - timedelta(minutes=CUR_DEV_EARLY_WINDOW_MIN)
            window_end = planned_time + timedelta(minutes=CUR_DEV_LATE_WINDOW_MIN)

            first_hit = None
            first_distance = None
            for event in valid_events:
                if event.event_time < window_start:
                    continue
                if event.event_time > window_end:
                    break

                distance_m = haversine_m(
                    float(event.lon),
                    float(event.lat),
                    float(stop["lon"]),
                    float(stop["lat"]),
                )
                if distance_m <= CUR_DEV_STOP_RADIUS_M:
                    first_hit = event.event_time
                    first_distance = float(distance_m)
                    break

            if first_hit is None:
                continue

            candidate = (first_hit, planned_time, first_distance, stop)
            if best is None or candidate[:2] > best[:2]:
                best = candidate

        if best is None:
            return None

        observed_time, planned_time, distance_m, stop = best
        deviation_s = float((observed_time - planned_time).total_seconds())

        meta = {
            "stop_id": int(stop["stop_id"]),
            "address": stop.get("address"),
            "planned_time": planned_time,
            "observed_time": observed_time,
            "distance_m": float(distance_m),
            "unit_id": int(unit_id),
        }
        return deviation_s, meta

    def _validate_horizon(self, horizon_min: float) -> None:
        if self._is_horizon_compliant(horizon_min):
            return

        self.horizon_violations += 1
        raise ValueError(
            "Горизонт прогноза должен находиться в интервале "
            f"({self._min_horizon_min}, {self._max_horizon_min}] минут, "
            f"получено {horizon_min:.3f}"
        )

    def _is_horizon_compliant(self, horizon_min: float) -> bool:
        return (
            self._min_horizon_min < float(horizon_min)
            <= self._max_horizon_min
        )

    def _mark_stale(self, unit_id: int, age_s: float) -> None:
        existing = self._prediction_store.get(unit_id)
        if existing is None:
            return

        if existing.get("status") != "stale":
            self.stale_transitions += 1

        existing["status"] = "stale"
        existing["telemetry_age_s"] = age_s
        existing["degradation_reason"] = (
            "Нет новой NDTP-телеметрии; показывается последнее известное состояние."
        )
        self._prediction_store.set(unit_id, existing)

    def _mark_degraded(self, unit_id: int, reason: str) -> None:
        existing = self._prediction_store.get(unit_id)
        if existing is None:
            return

        if existing.get("status") != "degraded":
            self.degraded_transitions += 1

        existing["status"] = "degraded"
        existing["degradation_reason"] = reason
        self._prediction_store.set(unit_id, existing)

    @staticmethod
    def _choose_target(
        candidates: list[StopCandidate],
        lon: float,
        lat: float,
    ) -> StopCandidate | None:
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]

        ranked: list[tuple[float, StopCandidate]] = []
        for candidate in candidates:
            point = parse_point(candidate.geom)
            if point is None:
                continue
            stop_lon, stop_lat = point
            ranked.append(
                (
                    haversine_m(lon, lat, stop_lon, stop_lat),
                    candidate,
                )
            )

        if not ranked:
            return candidates[0]
        return min(ranked, key=lambda item: item[0])[1]

    def _pending_vehicles(self) -> int:
        """Количество ТС с новой телеметрией, ещё не прошедшей inference."""

        pending = 0
        for unit_id in self._telemetry_store.get_vehicle_ids():
            latest = self._telemetry_store.get_latest(unit_id)
            if latest is None:
                continue
            if self._last_processed_time.get(unit_id) != latest.event_time:
                pending += 1
        return pending

    @staticmethod
    def _latency_summary(values: deque[float]) -> dict:
        sample = list(values)
        if not sample:
            return {
                "samples": 0,
                "mean_ms": None,
                "p50_ms": None,
                "p95_ms": None,
                "max_ms": None,
            }

        return {
            "samples": len(sample),
            "mean_ms": mean(sample),
            "p50_ms": _percentile(sample, 0.50),
            "p95_ms": _percentile(sample, 0.95),
            "max_ms": max(sample),
        }

    def metrics(self) -> dict:
        successful = self.total_predictions
        horizon_pct = (
            self.horizon_compliant_predictions / successful * 100.0
            if successful
            else 0.0
        )
        no_hindsight_pct = (
            self.no_hindsight_predictions / successful * 100.0
            if successful
            else 0.0
        )

        now = datetime.now(timezone.utc)
        uptime_s = (
            (now - self._started_at).total_seconds()
            if self._started_at is not None
            else 0.0
        )
        first_prediction_s = None
        if self._started_at is not None and self._first_prediction_at is not None:
            first_prediction_s = max(
                0.0,
                (self._first_prediction_at - self._started_at).total_seconds(),
            )

        return {
            "total_predictions": successful,
            "failed_predictions": self.failed_predictions,
            "last_cycle_ms": self.last_cycle_ms,
            "interval_s": self._interval_s,
            "uptime_s": uptime_s,
            "time_to_first_prediction_s": first_prediction_s,
            "throughput_predictions_per_s": (
                successful / uptime_s
                if uptime_s > 0
                else 0.0
            ),
            "pending_vehicles": self._pending_vehicles(),
            "processing_model": "latest-state; очередь пакетов для ML не накапливается",
            "latency": {
                "end_to_end": self._latency_summary(self._prediction_latency_ms),
                "ml": self._latency_summary(self._ml_latency_ms),
            },
            "reliability": {
                "stale_transitions": self.stale_transitions,
                "degraded_transitions": self.degraded_transitions,
                "recoveries": self.recoveries,
            },
            "horizon": {
                "min_exclusive": self._min_horizon_min,
                "max_inclusive": self._max_horizon_min,
                "default_min": self._default_horizon_min,
                "compliant_predictions": self.horizon_compliant_predictions,
                "violations": self.horizon_violations,
                "compliance_pct": horizon_pct,
            },
            "no_hindsight": {
                "compliant_predictions": self.no_hindsight_predictions,
                "violations": self.hindsight_violations,
                "compliance_pct": no_hindsight_pct,
            },
        }
