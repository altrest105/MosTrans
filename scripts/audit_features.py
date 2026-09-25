from pathlib import Path

import pandas as pd

from src.features import build_features


DATA_DIR = Path("dataset")


def load_test_data() -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    """Загрузить test-разметку, телеметрию и расписание."""

    labels = pd.read_csv(
        DATA_DIR / "labels" / "labels_test.csv"
    )

    traffic = pd.read_csv(
        DATA_DIR / "test" / "traffic.csv",
        low_memory=False,
    )

    schedule = pd.read_csv(
        DATA_DIR / "test" / "schedule.csv"
    )

    labels["T"] = pd.to_datetime(
        labels["T"]
    )

    labels["target_time_begin"] = pd.to_datetime(
        labels["target_time_begin"]
    )

    traffic["event_time"] = pd.to_datetime(
        traffic["event_time"]
    )

    return labels, traffic, schedule


def build_feature_table(
    labels: pd.DataFrame,
    traffic: pd.DataFrame,
    schedule: pd.DataFrame,
) -> pd.DataFrame:
    """
    Построить признаки для всех test-точек.

    Служебные поля sample_id, tr_id и target_delay_s
    добавляются только для последующего анализа.
    """

    traffic_by_tr = {
        tr_id: group.sort_values("event_time")
        for tr_id, group in traffic.groupby("tr_id")
    }

    schedule_by_tr = {
        tr_id: group
        for tr_id, group in schedule.groupby("tr_id")
    }

    empty_traffic = traffic.iloc[0:0]
    empty_schedule = schedule.iloc[0:0]

    rows: list[dict] = []
    total = len(labels)

    for index, sample in labels.iterrows():
        tr_id = sample["tr_id"]

        tr_traffic = traffic_by_tr.get(
            tr_id,
            empty_traffic,
        )

        tr_schedule = schedule_by_tr.get(
            tr_id,
            empty_schedule,
        )

        features = build_features(
            sample=sample,
            traffic=tr_traffic,
            schedule=tr_schedule,
        )

        features["sample_id"] = sample["sample_id"]
        features["tr_id"] = sample["tr_id"]
        features["target_delay_s"] = sample["target_delay_s"]

        rows.append(features)

        processed = index + 1

        if processed % 50 == 0 or processed == total:
            print(
                f"Построено признаков: "
                f"{processed}/{total}"
            )

    return pd.DataFrame(rows)


def print_basic_info(features: pd.DataFrame) -> None:
    """Вывести размер, колонки и количество пропусков."""

    print("\n=== ОБЩАЯ ИНФОРМАЦИЯ ===")
    print(f"Размер: {features.shape}")

    print("\nКолонки:")
    print(", ".join(features.columns))

    print("\nПропущенные значения:")

    print(
        features.isna()
        .sum()
        .sort_values(ascending=False)
        .to_string()
    )


def print_feature_statistics(features: pd.DataFrame) -> None:
    """Вывести описательную статистику числовых признаков."""

    print("\n=== СТАТИСТИКА ПРИЗНАКОВ ===")

    print(
        features.describe()
        .T
        .to_string()
    )


def print_missing_distance_rows(features: pd.DataFrame) -> None:
    """Показать строки, где не удалось определить расстояние до цели."""

    rows = features[
        features["distance_to_target_m"].isna()
    ]

    print("\n=== ПРОПУЩЕННОЕ РАССТОЯНИЕ ДО ЦЕЛИ ===")
    print(f"Количество строк: {len(rows)}")

    if rows.empty:
        print("Пропусков нет.")
        return

    print(
        rows[
            [
                "sample_id",
                "tr_id",
                "distance_to_target_m",
                "telemetry_age_s",
            ]
        ].to_string(index=False)
    )


def print_largest_distances(features: pd.DataFrame) -> None:
    """Показать точки с наибольшим расстоянием до целевой остановки."""

    print("\n=== НАИБОЛЬШИЕ РАССТОЯНИЯ ДО ЦЕЛИ ===")

    print(
        features.nlargest(
            10,
            "distance_to_target_m",
        )[
            [
                "sample_id",
                "tr_id",
                "distance_to_target_m",
                "cur_dev_s",
                "target_delay_s",
            ]
        ].to_string(index=False)
    )


def print_stalest_telemetry(features: pd.DataFrame) -> None:
    """Показать точки с наиболее старой доступной телеметрией."""

    print("\n=== САМАЯ СТАРАЯ ТЕЛЕМЕТРИЯ ===")

    print(
        features.nlargest(
            10,
            "telemetry_age_s",
        )[
            [
                "sample_id",
                "tr_id",
                "telemetry_age_s",
                "gps_points_10m",
            ]
        ].to_string(index=False)
    )


def print_no_fresh_gps(features: pd.DataFrame) -> None:
    """Показать точки без валидной GPS-телеметрии за последние 10 минут."""

    rows = features[
        features["gps_points_10m"] == 0
    ]

    print("\n=== НЕТ СВЕЖЕГО GPS ЗА 10 МИНУТ ===")
    print(f"Количество строк: {len(rows)}")

    if rows.empty:
        print("Таких строк нет.")
        return

    print(
        rows[
            [
                "sample_id",
                "tr_id",
                "telemetry_age_s",
                "last_speed",
                "distance_to_target_m",
                "cur_dev_s",
                "target_delay_s",
            ]
        ].to_string(index=False)
    )


def main() -> None:
    print("Загрузка test-данных...")

    labels, traffic, schedule = load_test_data()

    print("Построение признаков...")

    features = build_feature_table(
        labels=labels,
        traffic=traffic,
        schedule=schedule,
    )

    print_basic_info(features)
    print_feature_statistics(features)
    print_missing_distance_rows(features)
    print_largest_distances(features)
    print_stalest_telemetry(features)
    print_no_fresh_gps(features)


if __name__ == "__main__":
    main()