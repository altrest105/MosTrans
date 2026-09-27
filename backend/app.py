import logging
import math
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, HTTPException

from backend.config import (
    DEFAULT_HORIZON_MINUTES,
    HISTORY_RETENTION_MINUTES,
    MAX_HORIZON_MINUTES,
    MIN_HORIZON_MINUTES,
    ML_SERVICE_URL,
    NDTP_HOST,
    NDTP_PORT,
    PREDICTION_INTERVAL_S,
    REGISTRY_PATH,
    SCHEDULE_PATH,
    SCHEDULE_TIMEZONE,
    STALE_AFTER_S,
)
from backend.features.live import LiveFeatureBuilder
from backend.inference.client import MLServiceClient
from backend.ndtp.receiver import NDTPReceiver
from backend.prediction.engine import PredictionEngine
from backend.prediction.store import PredictionStore
from backend.schedule.service import ScheduleService
from backend.telemetry.state import TelemetryStore
from backend.time.clock import ScheduleClock
from backend.transport.registry import VehicleRegistry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

RUNTIME_PATCH_VERSION = "service-status-ui-2026-09-27-01"

telemetry_store = TelemetryStore(HISTORY_RETENTION_MINUTES)
vehicle_registry = VehicleRegistry(REGISTRY_PATH)
schedule_service = ScheduleService(SCHEDULE_PATH)
schedule_clock = ScheduleClock(
    local_timezone=SCHEDULE_TIMEZONE,
)
feature_builder = LiveFeatureBuilder()
ml_client = MLServiceClient(ML_SERVICE_URL)
prediction_store = PredictionStore()

def on_ndtp_telemetry(event):
    # Nav00 содержит UTC timestamp. Для сопоставления с суточным шаблоном
    # schedule_plan переводим его в московское локальное время, не подменяя дату.
    telemetry_store.add(schedule_clock.map_event(event))


ndtp_receiver = NDTPReceiver(
    host=NDTP_HOST,
    port=NDTP_PORT,
    on_telemetry=on_ndtp_telemetry,
)

prediction_engine = PredictionEngine(
    telemetry_store=telemetry_store,
    registry=vehicle_registry,
    schedule=schedule_service,
    feature_builder=feature_builder,
    ml_client=ml_client,
    prediction_store=prediction_store,
    interval_s=PREDICTION_INTERVAL_S,
    stale_after_s=STALE_AFTER_S,
    default_horizon_min=DEFAULT_HORIZON_MINUTES,
    min_horizon_min=MIN_HORIZON_MINUTES,
    max_horizon_min=MAX_HORIZON_MINUTES,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Запуск Backend")
    await ndtp_receiver.start()
    await prediction_engine.start()

    yield

    logger.info("Остановка Backend")
    await prediction_engine.stop()
    await ndtp_receiver.stop()
    await ml_client.close()


app = FastAPI(
    title="MosTrans Backend",
    description="NDTP ingestion, online features, ML orchestration and dashboard API.",
    version="1.1.0",
    lifespan=lifespan,
)


def _telemetry_status() -> dict:
    summaries = telemetry_store.get_vehicle_summaries()
    total = len(summaries)
    fresh = sum(
        float(item.get("telemetry_age_s", 0.0)) <= STALE_AFTER_S
        for item in summaries
    )
    stale = total - fresh

    return {
        "total_vehicles": total,
        "fresh_vehicles": fresh,
        "stale_vehicles": stale,
        "stale_after_s": STALE_AFTER_S,
    }


@app.get("/health")
async def health() -> dict:
    telemetry = _telemetry_status()
    return {
        "status": "ok" if ndtp_receiver.running and prediction_engine.running else "degraded",
        "ndtp_port": NDTP_PORT,
        "ndtp_receiver_running": ndtp_receiver.running,
        "prediction_engine_running": prediction_engine.running,
        "vehicles": telemetry["total_vehicles"],
        "fresh_vehicles": telemetry["fresh_vehicles"],
        "predictions": len(prediction_store.all()),
        "schedule_enabled": schedule_service.enabled,
        "schedule_clock": schedule_clock.status(),
        "runtime_patch_version": RUNTIME_PATCH_VERSION,
    }


@app.get("/system/status")
async def system_status() -> dict:
    """Сводный operational status для диспетчерского интерфейса."""

    telemetry = _telemetry_status()
    reasons: list[str] = []

    if not ndtp_receiver.running:
        reasons.append("NDTP-приёмник остановлен")

    if not prediction_engine.running:
        reasons.append("движок прогнозирования остановлен")

    if telemetry["total_vehicles"] == 0:
        state = "waiting"
    else:
        state = "ok"
        if telemetry["fresh_vehicles"] == 0:
            reasons.append("нет свежей NDTP-телеметрии")
        elif telemetry["stale_vehicles"] > 0:
            reasons.append(
                f"устарела телеметрия для {telemetry['stale_vehicles']} ТС"
            )

    ml_status = "ok"
    try:
        await ml_client.health()
    except Exception:  # noqa: BLE001
        ml_status = "unavailable"
        reasons.append("ML-сервис недоступен")

    if reasons:
        state = "degraded"

    predictions = prediction_store.all()
    last_known_state = bool(predictions) and state == "degraded"

    if state == "ok":
        message = "Система в норме"
    elif state == "waiting":
        message = "Ожидание телеметрии"
    else:
        message = "Деградация: " + "; ".join(reasons)
        if last_known_state:
            message += ". Показывается последнее известное состояние"

    return {
        "status": state,
        "message": message,
        "checked_at": datetime.now(timezone.utc),
        "telemetry": telemetry,
        "ml_service": ml_status,
        "last_known_state": last_known_state,
        "reasons": reasons,
    }


@app.get("/schedule/time")
async def schedule_time() -> dict:
    """Показать, как NDTP-время применяется к суточному расписанию."""

    return schedule_clock.status()


@app.get("/ml/health")
async def ml_health() -> dict:
    try:
        return {
            "status": "ok",
            "ml_service": await ml_client.health(),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "degraded",
            "ml_service": {
                "status": "unavailable",
                "error": str(exc),
            },
        }


def _service_meta(tr_id: int | None, current_time) -> dict:
    """Безопасно получить статус суточного графика для API."""

    if tr_id is None or not schedule_service.enabled:
        return {
            "status": "schedule_missing",
            "text": "Расписание не найдено",
            "first_planned_time": None,
            "last_planned_time": None,
        }
    return schedule_service.service_status(int(tr_id), current_time)


def _stop_payload(stop, *, source: str, distance_m: float | None = None) -> dict:
    return {
        "stop_id": stop.stop_id,
        "planned_time": stop.planned_time,
        "predicted_arrival_time": None,
        "predicted_deviation_s": None,
        "prediction_source": "unavailable",
        "selection_source": source,
        "distance_m": distance_m,
        "address": stop.address,
        "geom": stop.geom,
        "same_as_target": False,
    }


@app.get("/vehicles")
async def vehicles() -> list[dict]:
    """Текущие ТС, статус графика и следующая остановка текущего дня."""

    result = []
    for item in telemetry_store.get_vehicle_summaries():
        tr_id = vehicle_registry.get_tr_id(item["unit_id"])
        item["tr_id"] = tr_id
        item["next_stop"] = None

        service = _service_meta(tr_id, item["event_time"])
        item["service_status"] = service["status"]
        item["service_status_text"] = service["text"]
        item["service_first_planned_time"] = service["first_planned_time"]
        item["service_last_planned_time"] = service["last_planned_time"]

        # После конца суточного графика не подменяем следующую остановку
        # первым рейсом следующего дня и не ищем случайную ближайшую точку.
        if service["status"] not in {"finished", "schedule_missing"} and tr_id is not None:
            next_window = schedule_service.find_next_stop_window(
                tr_id=tr_id,
                current_time=item["event_time"],
                current_deviation_s=None,
            )
            if next_window is not None and next_window.candidates:
                stop = next_window.candidates[0]
                item["next_stop"] = _stop_payload(
                    stop,
                    source="schedule_next_stop",
                )
            else:
                nearest = schedule_service.find_nearest_route_stop(
                    tr_id=tr_id,
                    current_time=item["event_time"],
                    lon=item["lon"],
                    lat=item["lat"],
                )
                if nearest is not None:
                    item["next_stop"] = _stop_payload(
                        nearest.stop,
                        source="nearest_route_stop",
                        distance_m=nearest.distance_m,
                    )

        result.append(item)
    return result


@app.get("/vehicles/{unit_id}")
async def vehicle(unit_id: int) -> dict:
    latest = telemetry_store.get_latest(unit_id)
    if latest is None:
        raise HTTPException(status_code=404, detail="ТС не найдено")

    return {
        "unit_id": unit_id,
        "tr_id": vehicle_registry.get_tr_id(unit_id),
        "event_time": latest.event_time,
        "source_event_time": latest.source_event_time,
        "lat": latest.lat,
        "lon": latest.lon,
        "speed": latest.speed,
        "heading": latest.heading,
        "location_valid": latest.location_valid,
        "history_size": len(telemetry_store.get_history(unit_id)),
    }


@app.get("/vehicles/{unit_id}/route")
async def vehicle_route(unit_id: int) -> dict:
    """Плановый суточный маршрут выбранного ТС из schedule_plan.csv."""

    latest = telemetry_store.get_latest(unit_id)
    if latest is None:
        raise HTTPException(status_code=404, detail="ТС не найдено")

    tr_id = vehicle_registry.get_tr_id(unit_id)
    if tr_id is None:
        raise HTTPException(status_code=404, detail="unit_id не сопоставлен с tr_id")

    stops = schedule_service.route_for_day(tr_id, latest.event_time.date())
    if not stops:
        raise HTTPException(status_code=404, detail="Расписание для ТС не найдено")

    return {
        "unit_id": unit_id,
        "tr_id": tr_id,
        "date": latest.event_time.date(),
        "stops": stops,
    }


@app.get("/routes/active")
async def active_routes() -> list[dict]:
    """Плановые маршруты всех ТС, которые присутствуют в текущем NDTP-потоке."""

    routes: list[dict] = []
    seen: set[tuple[int, int]] = set()

    for unit_id in telemetry_store.get_vehicle_ids():
        latest = telemetry_store.get_latest(unit_id)
        if latest is None:
            continue

        tr_id = vehicle_registry.get_tr_id(unit_id)
        if tr_id is None:
            continue

        key = (int(unit_id), int(tr_id))
        if key in seen:
            continue
        seen.add(key)

        stops = schedule_service.route_for_day(tr_id, latest.event_time.date())
        if not stops:
            continue

        routes.append(
            {
                "unit_id": int(unit_id),
                "tr_id": int(tr_id),
                "date": latest.event_time.date(),
                "stops": stops,
            }
        )

    return routes


@app.get("/trails")
async def trails() -> list[dict]:
    """История фактического движения ТС с риском в каждой точке.

    Траектория накапливается с момента запуска Backend. Цвет каждого участка
    отражает риск, рассчитанный в тот момент: green/yellow/red. Это только
    реально полученные NDTP-координаты, без дорисованного маршрута.
    """

    return prediction_store.all_trails()


def _with_next_stop_fallback(item: dict) -> dict:
    """Добавить статус графика и следующую остановку текущего дня.

    Ключевое правило: если суточный график уже закончился, API прямо
    сообщает ``service_status=finished`` и не показывает остановку следующего
    дня как будто автобус продолжает текущий рейс.
    """

    result = dict(item)
    unit_id = result.get("unit_id")
    tr_id = result.get("tr_id")
    if tr_id is None and unit_id is not None:
        tr_id = vehicle_registry.get_tr_id(int(unit_id))

    lon = result.get("lon")
    lat = result.get("lat")
    current_time = result.get("prediction_time")

    if current_time is None and unit_id is not None:
        latest = telemetry_store.get_latest(int(unit_id))
        if latest is not None:
            current_time = latest.event_time
            lon = latest.lon if lon is None else lon
            lat = latest.lat if lat is None else lat

    service = _service_meta(tr_id, current_time) if current_time is not None else {
        "status": "schedule_missing",
        "text": "Расписание не найдено",
        "first_planned_time": None,
        "last_planned_time": None,
    }
    result["service_status"] = service["status"]
    result["service_status_text"] = service["text"]
    result["service_first_planned_time"] = service["first_planned_time"]
    result["service_last_planned_time"] = service["last_planned_time"]

    if service["status"] == "finished":
        result["next_stop"] = None
        result["forecast_status"] = "service_finished"
        return result

    if service["status"] == "schedule_missing":
        result.setdefault("next_stop", None)
        return result

    if result.get("next_stop") is not None:
        return result

    result["next_stop"] = None
    if tr_id is None or current_time is None or not schedule_service.enabled:
        return result

    current_deviation = result.get("current_deviation_s")
    deviation_s = None
    try:
        parsed_deviation = float(current_deviation)
        if math.isfinite(parsed_deviation):
            deviation_s = parsed_deviation
    except (TypeError, ValueError):
        pass

    next_window = schedule_service.find_next_stop_window(
        tr_id=int(tr_id),
        current_time=current_time,
        current_deviation_s=deviation_s,
    )
    if next_window is not None and next_window.candidates:
        stop = next_window.candidates[0]
        predicted_arrival = (
            None
            if deviation_s is None
            else stop.planned_time + timedelta(seconds=deviation_s)
        )
        result["next_stop"] = {
            **_stop_payload(stop, source="schedule_next_stop"),
            "predicted_arrival_time": predicted_arrival,
            "predicted_deviation_s": deviation_s,
            "prediction_source": (
                "current_deviation" if deviation_s is not None else "unavailable"
            ),
        }
        return result

    # GPS fallback используем только пока суточный график ещё не завершён.
    if lon is None or lat is None:
        return result

    nearest = schedule_service.find_nearest_route_stop(
        tr_id=int(tr_id),
        current_time=current_time,
        lon=float(lon),
        lat=float(lat),
    )
    if nearest is None:
        return result

    stop = nearest.stop
    predicted_arrival = (
        None
        if deviation_s is None
        else stop.planned_time + timedelta(seconds=deviation_s)
    )
    result["next_stop"] = {
        **_stop_payload(
            stop,
            source="nearest_route_stop",
            distance_m=nearest.distance_m,
        ),
        "predicted_arrival_time": predicted_arrival,
        "predicted_deviation_s": deviation_s,
        "prediction_source": (
            "current_deviation" if deviation_s is not None else "unavailable"
        ),
    }
    return result


@app.get("/predictions")
async def predictions() -> list[dict]:
    return [_with_next_stop_fallback(item) for item in prediction_store.all()]


@app.get("/predictions/{unit_id}")
async def prediction(unit_id: int) -> dict:
    item = prediction_store.get(unit_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Прогноз ещё не сформирован")
    return _with_next_stop_fallback(item)


@app.get("/metrics")
async def metrics() -> dict:
    return prediction_engine.metrics()


@app.get("/audit/performance")
async def performance_audit() -> dict:
    """Метрики производительности и надёжности для README/демо."""

    engine_metrics = prediction_engine.metrics()
    e2e = engine_metrics["latency"]["end_to_end"]
    p95_ms = e2e.get("p95_ms")

    return {
        "latency_target_ms": 2000.0,
        "latency_p95_ms": p95_ms,
        "latency_target_met": (
            p95_ms is not None and p95_ms < 2000.0
        ),
        "pending_vehicles": engine_metrics["pending_vehicles"],
        "time_to_first_prediction_s": engine_metrics[
            "time_to_first_prediction_s"
        ],
        "throughput_predictions_per_s": engine_metrics[
            "throughput_predictions_per_s"
        ],
        "reliability": engine_metrics["reliability"],
        "details": engine_metrics["latency"],
    }


@app.get("/audit/horizon")
async def horizon_audit() -> dict:
    """Проверяемое подтверждение горизонта (T+10, T+15] и отсутствия hindsight."""

    metrics = prediction_engine.metrics()
    latest = []

    for item in prediction_store.all():
        latest.append(
            {
                "unit_id": item.get("unit_id"),
                "prediction_time": item.get("prediction_time"),
                "telemetry_cutoff": item.get("telemetry_cutoff"),
                "forecast_for": item.get("forecast_for"),
                "horizon_min": item.get("horizon_min"),
                "horizon_compliant": item.get("horizon_compliant"),
            }
        )

    return {
        "rule": "Прогноз формируется в будущем окне (T+10, T+15] минут.",
        "default_horizon_min": DEFAULT_HORIZON_MINUTES,
        "metrics": metrics["horizon"],
        "no_hindsight": metrics["no_hindsight"],
        "latest_predictions": latest,
    }
