import json
from urllib.request import urlopen

BASE_URL = "http://127.0.0.1:8000"


def get_json(path: str) -> dict:
    """Получить JSON из локального Backend."""

    with urlopen(f"{BASE_URL}{path}", timeout=3) as response:  # noqa: S310
        return json.load(response)


def flag(value: bool) -> str:
    return "OK" if value else "FAIL"


def main() -> None:
    """Проверить ключевые runtime-критерии перед демонстрацией."""

    status = get_json("/system/status")
    horizon = get_json("/audit/horizon")
    performance = get_json("/audit/performance")
    metrics = get_json("/metrics")

    horizon_ok = (
        horizon["metrics"]["violations"] == 0
        and horizon["no_hindsight"]["violations"] == 0
    )

    latency_p95 = performance.get("latency_p95_ms")
    latency_ok = bool(performance.get("latency_target_met"))

    print("=== MosTrans runtime audit ===")
    print(f"System status:            {status['status']}")
    print(
        "Horizon (T+10..15):      "
        f"{flag(horizon_ok)} | "
        f"violations={horizon['metrics']['violations']}"
    )
    print(
        "No hindsight:            "
        f"{flag(horizon['no_hindsight']['violations'] == 0)}"
    )
    print(
        "Latency p95 < 2 s:       "
        f"{flag(latency_ok)} | "
        f"p95={latency_p95 if latency_p95 is not None else 'нет данных'} ms"
    )
    print(
        "Pending vehicles:        "
        f"{performance['pending_vehicles']}"
    )
    print(
        "Predictions:             "
        f"{metrics['total_predictions']} successful / "
        f"{metrics['failed_predictions']} failed"
    )
    print(
        "Recovery transitions:    "
        f"{metrics['reliability']['recoveries']}"
    )
    print(
        "Time to first prediction: "
        f"{metrics['time_to_first_prediction_s']} s"
    )


if __name__ == "__main__":
    main()
