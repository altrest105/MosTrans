import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from ml_service.predictor import Predictor
from ml_service.schemas import (
    PredictionRequest,
    PredictionResponse,
)


logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s | %(levelname)s | "
        "%(name)s | %(message)s"
    ),
)

logger = logging.getLogger(__name__)

predictor: Predictor | None = None


@asynccontextmanager
async def lifespan(
    app: FastAPI,
):
    """Загрузить модель при старте ML-сервиса."""

    global predictor

    logger.info(
        "Загрузка CatBoost-модели"
    )

    predictor = Predictor()

    logger.info(
        "Модель загружена: %s",
        predictor.model_path,
    )

    yield

    logger.info(
        "Остановка ML-сервиса"
    )


app = FastAPI(
    title="MosTrans ML Service",
    description=(
        "Сервис прогнозирования задержки "
        "городского транспорта."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health() -> dict:
    """Проверить состояние ML-сервиса."""

    return {
        "status": "ok",
        "model_loaded": predictor is not None,
    }


@app.post(
    "/predict",
    response_model=PredictionResponse,
)
async def predict(
    request: PredictionRequest,
) -> PredictionResponse:
    """Спрогнозировать задержку ТС."""

    if predictor is None:
        raise RuntimeError(
            "Модель ещё не загружена"
        )

    return predictor.predict(
        request
    )