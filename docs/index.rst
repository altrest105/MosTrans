MosTrans · документация решения
================================

MosTrans — realtime-система раннего прогнозирования отклонений городского транспорта.
Backend принимает NDTP-телеметрию, сопоставляет её с расписанием, формирует признаки и
вызывает независимый CatBoost ML Service. Dashboard визуализирует текущее положение ТС,
историю риска и прогноз на горизонте 10–15 минут.

.. toctree::
   :maxdepth: 2
   :caption: Содержание

   architecture
   backend
   ml_service
   api

Быстрые ссылки
--------------

* Backend Swagger: ``http://localhost:8000/docs``
* Backend ReDoc: ``http://localhost:8000/redoc``
* ML Swagger: ``http://localhost:8001/docs``
* ML ReDoc: ``http://localhost:8001/redoc``
