"""Быстрая проверка симметричной классификации отклонений."""

from backend.prediction.rules import classify_risk, deviation_direction


def main() -> None:
    cases = [
        (-240, "red", "early"),
        (-90, "yellow", "early"),
        (-30, "green", "early"),
        (0, "green", "on_time"),
        (30, "green", "late"),
        (90, "yellow", "late"),
        (240, "red", "late"),
    ]

    for value, expected_risk, expected_direction in cases:
        risk = classify_risk(value)
        direction = deviation_direction(value)
        assert risk == expected_risk, (value, risk, expected_risk)
        assert direction == expected_direction, (value, direction, expected_direction)

    print("Deviation rules: OK")
    print("Риск одинаково учитывает опоздание и опережение по модулю отклонения.")


if __name__ == "__main__":
    main()
