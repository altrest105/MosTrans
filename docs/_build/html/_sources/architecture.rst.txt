Архитектура
===========

Основной realtime-контур
------------------------

::

   NDTP emulator / live stream
              |
              | TCP :9201
              v
        Backend :8000
        - NDTP parser
        - telemetry state
        - schedule matching
        - online features
        - prediction orchestration
              |
              | HTTP POST /predict
              v
       ML Service :8001
       - CatBoost inference
              |
              v
       Backend prediction store
              |
              v
       Frontend / dashboard

Горизонт прогноза
-----------------

Production runtime использует фиксированную точку 12.5 минуты, находящуюся внутри
обязательного интервала 10–15 минут. Backend формирует признаки только по телеметрии,
доступной к моменту прогнозирования T.

Основные данные
---------------

``traffic.csv`` используется для связи ``unit_id -> tr_id``. ``schedule_plan.csv`` содержит
эталонные плановые остановки. ``points.csv`` используется в offline ML-проверке, но не является
источником target в live runtime.
