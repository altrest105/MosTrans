"""Настройка OpenAPI/Swagger для Backend MosTrans.

Модуль не содержит бизнес-логики. Он только добавляет понятные названия,
описания, группы методов и примеры ответов в автоматически генерируемую
FastAPI-схему OpenAPI.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute


OPENAPI_TAGS = [
    {
        "name": "Система",
        "description": "Состояние Backend и сводный статус realtime-контура.",
    },
    {
        "name": "Телеметрия",
        "description": "Текущее состояние транспортных средств из потока NDTP.",
    },
    {
        "name": "Расписание",
        "description": "Сопоставление live-времени с эталонным суточным расписанием.",
    },
    {
        "name": "Прогнозы",
        "description": "Результаты CatBoost-прогноза отклонения на горизонте 10–15 минут.",
    },
    {
        "name": "Траектории",
        "description": "Фактически пройденные GPS-траектории и история риска.",
    },
    {
        "name": "ML-интеграция",
        "description": "Проверка связи Backend с независимым ML-сервисом.",
    },
    {
        "name": "Метрики",
        "description": "Runtime-производительность и аудит корректности прогнозного контура.",
    },
]


ROUTE_DOCS: dict[tuple[str, str], dict[str, str]] = {
    ("GET", "/health"): {
        "tag": "Система",
        "summary": "Проверить состояние Backend",
        "description": (
            "Показывает состояние NDTP-приёмника, prediction engine, расписания и число "
            "активных транспортных средств и прогнозов. Используется Docker healthcheck."
        ),
    },
    ("GET", "/system/status"): {
        "tag": "Система",
        "summary": "Получить сводный статус системы",
        "description": (
            "Operational-статус для диспетчерского интерфейса: свежесть телеметрии, "
            "доступность ML-сервиса и признаки деградации."
        ),
    },
    ("GET", "/schedule/time"): {
        "tag": "Расписание",
        "summary": "Проверить часы расписания",
        "description": (
            "Показывает параметры преобразования NDTP timestamp в локальное московское "
            "время, используемое для суточного шаблона schedule_plan.csv."
        ),
    },
    ("GET", "/ml/health"): {
        "tag": "ML-интеграция",
        "summary": "Проверить доступность ML-сервиса",
        "description": "Backend выполняет health-check независимого ML API.",
    },
    ("GET", "/vehicles"): {
        "tag": "Телеметрия",
        "summary": "Получить активные транспортные средства",
        "description": (
            "Возвращает последнее NDTP-состояние каждого известного unit_id: координаты, "
            "скорость, свежесть данных и связанный tr_id."
        ),
    },
    ("GET", "/vehicles/{unit_id}"): {
        "tag": "Телеметрия",
        "summary": "Получить состояние одного ТС",
        "description": "Детальное последнее состояние транспортного средства по unit_id.",
    },
    ("GET", "/vehicles/{unit_id}/route"): {
        "tag": "Расписание",
        "summary": "Получить плановые остановки ТС",
        "description": (
            "Служебный endpoint планового расписания конкретного ТС. Геометрия между "
            "остановками не трактуется как фактическая дорожная траектория."
        ),
    },
    ("GET", "/routes/active"): {
        "tag": "Расписание",
        "summary": "Получить расписания активных ТС",
        "description": "Служебное представление плановых остановок активных ТС.",
    },
    ("GET", "/trails"): {
        "tag": "Траектории",
        "summary": "Получить фактически пройденные траектории",
        "description": (
            "Возвращает накопленные за текущую сессию GPS-точки. Точки содержат "
            "состояние риска, поэтому dashboard окрашивает пройденный путь во времени."
        ),
    },
    ("GET", "/predictions"): {
        "tag": "Прогнозы",
        "summary": "Получить последние прогнозы всех ТС",
        "description": (
            "Последний доступный результат prediction pipeline для каждого ТС. "
            "Основной горизонт системы — 12.5 минуты, внутри обязательного окна 10–15 минут."
        ),
    },
    ("GET", "/predictions/{unit_id}"): {
        "tag": "Прогнозы",
        "summary": "Получить прогноз конкретного ТС",
        "description": (
            "Прогноз отклонения, уровень риска, текущие производные признаки, целевая "
            "остановка и служебные признаки качества сопоставления расписания."
        ),
    },
    ("GET", "/metrics"): {
        "tag": "Метрики",
        "summary": "Получить runtime-метрики",
        "description": "Сводные счётчики prediction engine для страницы доказательных метрик.",
    },
    ("GET", "/audit/performance"): {
        "tag": "Метрики",
        "summary": "Получить метрики производительности",
        "description": (
            "Latency полного prediction pipeline и вызова ML-сервиса, число измерений, "
            "ошибок и текущая частота формирования прогнозов."
        ),
    },
    ("GET", "/audit/horizon"): {
        "tag": "Метрики",
        "summary": "Проверить горизонт 10–15 минут",
        "description": (
            "Проверяет runtime-прогнозы на соблюдение допустимого горизонта и на то, "
            "что для прогноза использовались только данные, доступные к моменту T."
        ),
    },
}


RESPONSE_EXAMPLES: dict[tuple[str, str], Any] = {
    ("GET", "/health"): {
        "status": "ok",
        "ndtp_port": 9201,
        "ndtp_receiver_running": True,
        "prediction_engine_running": True,
        "vehicles": 13,
        "fresh_vehicles": 13,
        "predictions": 13,
        "schedule_enabled": True,
    },
    ("GET", "/vehicles/{unit_id}"): {
        "unit_id": 985940,
        "tr_id": 131672,
        "lat": 55.7932584,
        "lon": 37.5942241,
        "speed": 41.0,
        "heading": 164.0,
        "telemetry_age_s": 1.2,
    },
    ("GET", "/predictions/{unit_id}"): {
        "unit_id": 985940,
        "tr_id": 131672,
        "horizon_min": 12.5,
        "horizon_compliant": True,
        "deviation_s": 78.4,
        "deviation_direction": "late",
        "risk": "yellow",
        "current_deviation_s": 42.0,
        "current_deviation_source": "last_known",
        "average_speed_kmh": 21.7,
        "dwell_time_s": 35.0,
        "ml_latency_ms": 1.1,
        "status": "ok",
    },
}


def _apply_route_docs(app: FastAPI) -> None:
    """Применить summary/description/tags к зарегистрированным FastAPI routes."""

    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in route.methods or set():
            doc = ROUTE_DOCS.get((method.upper(), route.path))
            if not doc:
                continue
            route.tags = [doc["tag"]]
            route.summary = doc["summary"]
            route.description = doc["description"]
            break


def configure_backend_openapi(app: FastAPI) -> None:
    """Настроить человекочитаемый Swagger/OpenAPI Backend без изменения API."""

    app.title = "MosTrans · Backend API"
    app.description = (
        "Backend realtime-системы раннего прогнозирования отклонений городского транспорта. "
        "Сервис принимает NDTP-телеметрию, сопоставляет ТС с расписанием, рассчитывает "
        "онлайн-признаки, вызывает отдельный ML-сервис и отдаёт данные диспетчерскому dashboard."
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

        for (method, path), example in RESPONSE_EXAMPLES.items():
            operation = schema.get("paths", {}).get(path, {}).get(method.lower())
            if not operation:
                continue
            response = operation.setdefault("responses", {}).setdefault(
                "200", {"description": "Успешный ответ"}
            )
            response["description"] = "Успешный ответ"
            response.setdefault("content", {}).setdefault("application/json", {})[
                "example"
            ] = example

        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi
