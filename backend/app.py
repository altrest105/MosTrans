import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from backend.ndtp.receiver import NDTPReceiver
from backend.telemetry.state import TelemetryStore
from backend.transport.registry import VehicleRegistry
from backend.inference.client import MLServiceClient


logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s | "
        "%(levelname)s | "
        "%(name)s | "
        "%(message)s"
    ),
)

logger = logging.getLogger(__name__)


ml_client = MLServiceClient()

telemetry_store = TelemetryStore(
    retention_minutes=15
)

vehicle_registry = VehicleRegistry()

logger.info(
    "Загружено соответствий unit_id → tr_id: %d",
    len(vehicle_registry),
)

ndtp_receiver = NDTPReceiver(
    host="0.0.0.0",
    port=9201,
    on_telemetry=telemetry_store.add,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Управлять запуском и остановкой Backend."""

    logger.info(
        "Запуск Backend"
    )

    await ndtp_receiver.start()

    try:
        yield

    finally:
        logger.info(
            "Остановка Backend"
        )

        await ndtp_receiver.stop()
        await ml_client.close()


app = FastAPI(
    title="MosTrans Backend",
    description=(
        "Backend системы раннего прогнозирования "
        "изменений графика движения транспорта."
    ),
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health() -> dict[str, str]:
    """Проверить состояние Backend."""

    return {
        "status": "ok",
    }


@app.get("/vehicles")
async def get_vehicles() -> list[dict]:
    """Получить текущее состояние всех известных ТС."""

    vehicles = (
        telemetry_store
        .get_vehicle_summaries()
    )

    for vehicle in vehicles:
        vehicle["tr_id"] = (
            vehicle_registry.get_tr_id(
                vehicle["unit_id"]
            )
        )

    return vehicles


@app.get("/vehicles/{unit_id}")
async def get_vehicle(
    unit_id: int,
) -> dict:
    """Получить текущее состояние одного ТС."""

    latest = telemetry_store.get_latest(
        unit_id
    )

    if latest is None:
        raise HTTPException(
            status_code=404,
            detail="ТС не найдено",
        )

    history = telemetry_store.get_history(
        unit_id
    )

    return {
        "unit_id": latest.unit_id,
        "tr_id": vehicle_registry.get_tr_id(
            latest.unit_id
        ),
        "event_time": latest.event_time,
        "lat": latest.lat,
        "lon": latest.lon,
        "speed": latest.speed,
        "heading": latest.heading,
        "location_valid": latest.location_valid,
        "history_size": len(history),
    }

@app.get("/ml/health")
async def ml_health() -> dict:
    """Проверить связь Backend с ML-сервисом."""

    try:
        ml_status = await ml_client.health()

        return {
            "status": "ok",
            "ml_service": ml_status,
        }

    except Exception as exc:
        return {
            "status": "degraded",
            "ml_service": {
                "status": "unavailable",
                "error": str(exc),
            },
        }