from pathlib import Path
from time import perf_counter
import os

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor

from ml_service.schemas import PredictionRequest, PredictionResponse

FEATURE_NAMES = (
    "cur_dev_s",
    "horizon_min",
    "hour",
    "last_speed",
    "telemetry_age_s",
    "mean_speed_10m",
    "max_speed_10m",
    "stopped_share_10m",
    "gps_points_10m",
    "distance_to_target_m",
)

DEFAULT_MODEL_PATH = Path(
    os.getenv(
        "MODEL_PATH",
        str(Path(__file__).resolve().parents[1] / "ml" / "artifacts" / "catboost_final.cbm"),
    )
)


class Predictor:
    """CatBoost online inference."""

    def __init__(self, model_path: Path = DEFAULT_MODEL_PATH) -> None:
        if not model_path.exists():
            raise FileNotFoundError(f"Модель не найдена: {model_path}")

        self._model = CatBoostRegressor()
        self._model.load_model(str(model_path))
        self.model_path = model_path

    def predict(self, request: PredictionRequest) -> PredictionResponse:
        values = request.model_dump()
        row = {
            name: np.nan if values[name] is None else float(values[name])
            for name in FEATURE_NAMES
        }
        features = pd.DataFrame([row], columns=FEATURE_NAMES)

        started = perf_counter()
        prediction = float(self._model.predict(features)[0])
        latency_ms = (perf_counter() - started) * 1000.0

        return PredictionResponse(
            prediction=prediction,
            latency_ms=latency_ms,
        )
