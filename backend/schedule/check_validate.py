from pathlib import Path

import pandas as pd

from backend.schedule.service import ScheduleService


PROJECT_ROOT = Path(__file__).resolve().parents[2]

POINTS_PATH = (
    PROJECT_ROOT
    / "ml"
    / "dataset"
    / "validate"
    / "points.csv"
)

SCHEDULE_PATH = (
    PROJECT_ROOT
    / "ml"
    / "dataset"
    / "validate"
    / "schedule_plan.csv"
)


def main() -> None:
    """Проверить поиск целевого времени и остановок на validate."""

    points = pd.read_csv(
        POINTS_PATH
    )

    points["T"] = pd.to_datetime(
        points["T"]
    )

    points["target_time_begin"] = pd.to_datetime(
        points["target_time_begin"]
    )

    schedule_service = ScheduleService(
        schedule_path=SCHEDULE_PATH
    )

    print(
        f"ТС в расписании: "
        f"{schedule_service.vehicle_count()}"
    )

    total = len(points)

    target_found = 0
    time_matches = 0
    stop_matches = 0
    full_matches = 0
    ambiguous_count = 0

    mismatches: list[dict] = []

    for _, sample in points.iterrows():
        target = schedule_service.find_target_window(
            tr_id=int(
                sample["tr_id"]
            ),
            prediction_time=sample["T"],
        )

        if target is None:
            mismatches.append(
                {
                    "sample_id": sample["sample_id"],
                    "reason": "target_not_found",
                    "expected_stop": int(
                        sample["target_stop_id"]
                    ),
                    "expected_time": sample[
                        "target_time_begin"
                    ],
                }
            )

            continue

        target_found += 1

        if target.is_ambiguous:
            ambiguous_count += 1

        time_match = (
            pd.Timestamp(
                target.planned_time
            )
            == sample["target_time_begin"]
        )

        candidate_stop_ids = {
            candidate.stop_id
            for candidate in target.candidates
        }

        expected_stop_id = int(
            sample["target_stop_id"]
        )

        stop_match = (
            expected_stop_id
            in candidate_stop_ids
        )

        if time_match:
            time_matches += 1

        if stop_match:
            stop_matches += 1

        if time_match and stop_match:
            full_matches += 1

        else:
            mismatches.append(
                {
                    "sample_id": sample["sample_id"],
                    "reason": "mismatch",
                    "expected_stop": expected_stop_id,
                    "candidate_stops": sorted(
                        candidate_stop_ids
                    ),
                    "expected_time": sample[
                        "target_time_begin"
                    ],
                    "found_time": target.planned_time,
                    "horizon_min": target.horizon_min,
                    "ambiguous": target.is_ambiguous,
                }
            )

    print("\n=== ПРОВЕРКА РАСПИСАНИЯ ===")

    print(
        f"Всего точек:              "
        f"{total}"
    )

    print(
        f"Target найден:            "
        f"{target_found}/{total}"
    )

    print(
        f"Совпадение времени:       "
        f"{time_matches}/{total}"
    )

    print(
        f"Target stop среди кандидатов: "
        f"{stop_matches}/{total}"
    )

    print(
        f"Полное совпадение:        "
        f"{full_matches}/{total}"
    )

    print(
        f"Неоднозначных точек:      "
        f"{ambiguous_count}/{total}"
    )

    accuracy = (
        full_matches / total
        if total
        else 0.0
    )

    print(
        f"Точность:                 "
        f"{accuracy:.2%}"
    )

    if mismatches:
        print("\nПервые несовпадения:")

        print(
            pd.DataFrame(
                mismatches
            )
            .head(20)
            .to_string(index=False)
        )

    else:
        print(
            "\nВсе целевые события "
            "определены корректно."
        )


if __name__ == "__main__":
    main()