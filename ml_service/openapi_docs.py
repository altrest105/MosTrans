"""Настройка OpenAPI/Swagger независимого ML-сервиса MosTrans."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute


OPENAPI_TAGS = [
    {
        "name": "Сервис",
        "description": "Состояние ML-контейнера и загрузки CatBoost-модели.",
    },
    {
        "name": "Инференс",
        "description": "Синхронный прогноз отклонения ТС по 10 online-признакам.",
    },
]

FEATURE_DESCRIPTIONS = {
    "cur_dev_s": "Текущее отклонение на последней подтверждённо пройденной остановке, сек.",
    "horizon_min": "Горизонт прогноза в минутах. Production runtime использует 12.5.",
    "hour": "Локальный час момента прогнозирования T.",
    "last_speed": "Последняя известная скорость ТС, км/ч.",
    "telemetry_age_s": "Возраст последней телеметрии относительно T, сек.",
    "mean_speed_10m": "Средняя скорость по валидной телеметрии за последние 10 минут, км/ч.",
    "max_speed_10m": "Максимальная скорость за последние 10 минут, км/ч.",
    "stopped_share_10m": "Доля наблюдений за 10 минут со скоростью не выше 1 км/ч.",
    "gps_points_10m": "Количество валидных GPS-точек за последние 10 минут.",
    "distance_to_target_m": "Расстояние от последней GPS-точки до целевой остановки, м.",
}

REQUEST_EXAMPLE = {
    "cur_dev_s": 42.0,
    "horizon_min": 12.5,
    "hour": 18.0,
    "last_speed": 31.0,
    "telemetry_age_s": 1.0,
    "mean_speed_10m": 22.4,
    "max_speed_10m": 48.0,
    "stopped_share_10m": 0.12,
    "gps_points_10m": 82.0,
    "distance_to_target_m": 2350.0,
}

RESPONSE_EXAMPLE = {
    "prediction": 76.8,
    "latency_ms": 1.2,
}


def _apply_route_docs(app: FastAPI) -> None:
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if route.path == "/health":
            route.tags = ["Сервис"]
            route.summary = "Проверить состояние ML-сервиса"
            route.description = "Показывает, загружена ли CatBoost-модель и готов ли сервис к inference."
        elif route.path == "/predict":
            route.tags = ["Инференс"]
            route.summary = "Спрогнозировать отклонение ТС"
            route.description = (
                "Принимает 10 признаков, сформированных Backend только из данных, доступных "
                "на момент T, и возвращает прогноз отклонения в секундах вместе с latency модели. "
                "Положительное значение означает опоздание, отрицательное — опережение."
            )


def configure_ml_openapi(app: FastAPI) -> None:
    """Настроить Swagger ML-сервиса и добавить описание признаков/пример inference."""

    app.title = " MosTrans· ML Service API"
    app.description = (
        "Независимый сервис CatBoost-инференса для раннего прогноза отклонения транспорта. "
        "Backend формирует online-признаки и вызывает POST /predict."
    )
    app.version = "1.0"
    app.openapi_tags = OPENAPI_TAGS
    _apply_route_docs(app)
    app.openapi_schema = None

    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema

        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
            tags=app.openapi_tags,
        )
        schema["info"]["contact"] = {"name": "Команда Ботанский клуб"}

        request_schema = (
            schema.get("components", {})
            .get("schemas", {})
            .get("PredictionRequest", {})
        )
        for name, prop in request_schema.get("properties", {}).items():
            if name in FEATURE_DESCRIPTIONS:
                prop["description"] = FEATURE_DESCRIPTIONS[name]

        predict = schema.get("paths", {}).get("/predict", {}).get("post")
        if predict:
            content = predict.get("requestBody", {}).get("content", {}).get("application/json")
            if content is not None:
                content["example"] = REQUEST_EXAMPLE
            response = predict.setdefault("responses", {}).setdefault(
                "200", {"description": "Прогноз успешно рассчитан"}
            )
            response["description"] = "Прогноз успешно рассчитан"
            response.setdefault("content", {}).setdefault("application/json", {})[
                "example"
            ] = RESPONSE_EXAMPLE

        health = schema.get("paths", {}).get("/health", {}).get("get")
        if health:
            response = health.setdefault("responses", {}).setdefault(
                "200", {"description": "Сервис доступен"}
            )
            response["description"] = "Сервис доступен"
            response.setdefault("content", {}).setdefault("application/json", {})[
                "example"
            ] = {"status": "ok", "model_loaded": True}

        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi
