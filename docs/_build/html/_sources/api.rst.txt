API и Swagger
=============

Backend API
-----------

После запуска системы интерактивная спецификация Backend доступна по адресу
``http://localhost:8000/docs``. Альтернативное представление ReDoc —
``http://localhost:8000/redoc``.

Основные группы методов: состояние системы, NDTP-телеметрия, расписание, прогнозы,
фактические траектории, ML-интеграция и runtime-метрики.

ML Service API
--------------

Swagger ML-сервиса доступен по адресу ``http://localhost:8001/docs``, ReDoc —
``http://localhost:8001/redoc``.

Основной метод ``POST /predict`` принимает 10 online-признаков и возвращает прогноз
отклонения в секундах и чистую latency CatBoost-инференса.

OpenAPI JSON
------------

Машиночитаемые спецификации доступны в стандартных FastAPI endpoint'ах:

* Backend: ``http://localhost:8000/openapi.json``
* ML Service: ``http://localhost:8001/openapi.json``
