FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# В проекте один общий requirements.txt для Backend и ML Service.
COPY requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install -r /app/requirements.txt

# Backend-код.
COPY backend /app/backend

# Runtime использует validate/traffic.csv и validate/schedule_plan.csv.
# Сохраняем структуру путей, которую ожидает backend/config.py.
COPY ml/dataset/validate /app/ml/dataset/validate

EXPOSE 8000 9201

CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]