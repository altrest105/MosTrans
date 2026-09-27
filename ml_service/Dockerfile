FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# CatBoost использует OpenMP; libgomp нужен в slim-образе.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Тот же общий requirements.txt, что и у Backend.
COPY requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install -r /app/requirements.txt

COPY ml_service /app/ml_service

# Путь совпадает с дефолтным MODEL_PATH в ml_service/predictor.py.
COPY ml/artifacts /app/ml/artifacts

EXPOSE 8001

CMD ["uvicorn", "ml_service.app:app", "--host", "0.0.0.0", "--port", "8001"]