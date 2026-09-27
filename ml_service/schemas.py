from pydantic import BaseModel


class PredictionRequest(BaseModel):
    cur_dev_s: float | None = None
    horizon_min: float | None = None
    hour: float | None = None
    last_speed: float | None = None
    telemetry_age_s: float | None = None
    mean_speed_10m: float | None = None
    max_speed_10m: float | None = None
    stopped_share_10m: float | None = None
    gps_points_10m: float | None = None
    distance_to_target_m: float | None = None


class PredictionResponse(BaseModel):
    prediction: float
    latency_ms: float
