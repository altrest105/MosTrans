import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from ml_service.predictor import Predictor
from ml_service.schemas import PredictionRequest, PredictionResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

predictor: Predictor | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global predictor
    predictor = Predictor()
    logger.info("CatBoost загружен: %s", predictor.model_path)
    yield
    logger.info("Остановка ML Service")


app = FastAPI(
    title="MosTrans ML Service",
    description="CatBoost inference service for transport delay prediction.",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok" if predictor is not None else "starting",
        "model_loaded": predictor is not None,
    }


@app.post("/predict", response_model=PredictionResponse)
async def predict(request: PredictionRequest) -> PredictionResponse:
    if predictor is None:
        raise HTTPException(status_code=503, detail="Модель ещё не загружена")
    return predictor.predict(request)
