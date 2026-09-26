from pathlib import Path
from time import perf_counter

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor

from ml_service.schemas import (
    PredictionRequest,
    PredictionResponse,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_MODEL_PATH = (
    PROJECT_ROOT
    / "ml"
    / "artifacts"
    / "catboost_final.cbm"
)

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


class Predictor:
    """Обёртка над CatBoost для online-инференса."""

    def __init__(
        self,
        model_path: Path = DEFAULT_MODEL_PATH,
    ) -> None:
        if not model_path.exists():
            raise FileNotFoundError(
                f"Модель не найдена: {model_path}"
            )

        self._model = CatBoostRegressor()

        self._model.load_model(
            str(model_path)
        )

        self._model_path = model_path

    @property
    def model_path(self) -> Path:
        """Получить путь к загруженной модели."""

        return self._model_path

    def predict(
        self,
        request: PredictionRequest,
    ) -> PredictionResponse:
        """Выполнить прогноз задержки в секундах."""

        row = request.model_dump()

        feature_values = {
            feature_name: (
                np.nan
                if row[feature_name] is None
                else float(row[feature_name])
            )
            for feature_name in FEATURE_NAMES
        }

        features = pd.DataFrame(
            [feature_values],
            columns=FEATURE_NAMES,
        )

        started_at = perf_counter()

        prediction = float(
            self._model.predict(
                features
            )[0]
        )

        latency_ms = (
            perf_counter() - started_at
        ) * 1000.0

        return PredictionResponse(
            prediction=prediction,
            latency_ms=latency_ms,
        )