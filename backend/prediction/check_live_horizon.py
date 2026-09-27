import json
import os
from datetime import datetime
from urllib.request import urlopen

BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")


def parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def main() -> None:
    with urlopen(f"{BACKEND_URL}/audit/horizon", timeout=5) as response:  # noqa: S310
        data = json.load(response)

    latest = data.get("latest_predictions", [])
    failures: list[str] = []

    for item in latest:
        unit_id = item.get("unit_id")
        horizon = float(item.get("horizon_min"))
        prediction_time = parse_datetime(item["prediction_time"])
        telemetry_cutoff = parse_datetime(item["telemetry_cutoff"])
        forecast_for = parse_datetime(item["forecast_for"])

        if not (10.0 < horizon <= 15.0):
            failures.append(f"unit_id={unit_id}: horizon={horizon}")

        if telemetry_cutoff > prediction_time:
            failures.append(
                f"unit_id={unit_id}: telemetry_cutoff позже T"
            )

        actual_horizon = (forecast_for - prediction_time).total_seconds() / 60.0
        if abs(actual_horizon - horizon) > 1e-6:
            failures.append(
                f"unit_id={unit_id}: forecast_for не соответствует horizon"
            )

    metrics = data.get("metrics", {})
    no_hindsight = data.get("no_hindsight", {})

    print("=== LIVE HORIZON AUDIT ===")
    print(f"Последних прогнозов: {len(latest)}")
    print(
        "Накоплено compliant: "
        f"{metrics.get('compliant_predictions', 0)}"
    )
    print(
        "Нарушений горизонта: "
        f"{metrics.get('violations', 0)}"
    )
    print(
        "Horizon compliance: "
        f"{metrics.get('compliance_pct', 0):.2f}%"
    )
    print(
        "Hindsight violations: "
        f"{no_hindsight.get('violations', 0)}"
    )

    if failures:
        print("\nОШИБКИ:")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)

    print("\nOK: все текущие прогнозы соблюдают (T+10, T+15] и не используют данные после T.")


if __name__ == "__main__":
    main()
