from pathlib import Path
import os

PROJECT_ROOT = Path(__file__).resolve().parents[1]

BACKEND_HOST = os.getenv("BACKEND_HOST", "0.0.0.0")
BACKEND_PORT = int(os.getenv("BACKEND_PORT", "8000"))
NDTP_HOST = os.getenv("NDTP_HOST", "0.0.0.0")
NDTP_PORT = int(os.getenv("NDTP_PORT", "9201"))

ML_SERVICE_URL = os.getenv("ML_SERVICE_URL", "http://127.0.0.1:8001")

# Backend проверяет новые NDTP-состояния раз в секунду. Одна и та же
# телеметрия повторно через ML не прогоняется.
PREDICTION_INTERVAL_S = float(os.getenv("PREDICTION_INTERVAL_S", "1"))
STALE_AFTER_S = float(os.getenv("STALE_AFTER_S", "30"))
HISTORY_RETENTION_MINUTES = int(os.getenv("HISTORY_RETENTION_MINUTES", "15"))

# Оперативный прогноз фиксирован на 12.5 минуты. Это находится строго внутри
# обязательного окна (T+10, T+15] и соответствует выбранному runtime-сценарию.
MIN_HORIZON_MINUTES = float(os.getenv("MIN_HORIZON_MINUTES", "10"))
MAX_HORIZON_MINUTES = float(os.getenv("MAX_HORIZON_MINUTES", "15"))
DEFAULT_HORIZON_MINUTES = float(os.getenv("DEFAULT_HORIZON_MINUTES", "12.5"))

DEFAULT_VALIDATE_DIR = PROJECT_ROOT / "ml" / "dataset" / "validate"
REGISTRY_PATH = Path(
    os.getenv(
        "REGISTRY_PATH",
        str(DEFAULT_VALIDATE_DIR / "traffic.csv"),
    )
)
SCHEDULE_PATH = Path(
    os.getenv(
        "SCHEDULE_PATH",
        str(DEFAULT_VALIDATE_DIR / "schedule_plan.csv"),
    )
)

# schedule_plan.csv используется как повторяющийся суточный шаблон.
SCHEDULE_TIMEZONE = os.getenv("SCHEDULE_TIMEZONE", "Europe/Moscow")
