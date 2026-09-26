from pathlib import Path

import pandas as pd
from sklearn.metrics import mean_absolute_error


ML_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ML_ROOT / "dataset"


def load_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Загрузить train/test-разметку и точки validate."""

    train_labels = pd.read_csv(
        DATA_DIR / "labels" / "labels_train.csv"
    )

    test_labels = pd.read_csv(
        DATA_DIR / "labels" / "labels_test.csv"
    )

    validate_points = pd.read_csv(
        DATA_DIR / "validate" / "points.csv"
    )

    return train_labels, test_labels, validate_points


def print_dataset_info(
    train_labels: pd.DataFrame,
    test_labels: pd.DataFrame,
    validate_points: pd.DataFrame,
) -> None:
    """Вывести основную информацию о размерах и структуре датасета."""

    print("=== ДАТАСЕТ ===")
    print(f"Train:    {train_labels.shape}")
    print(f"Test:     {test_labels.shape}")
    print(f"Validate: {validate_points.shape}")

    print("\nКолонки train:")
    print(", ".join(train_labels.columns))

    print("\nПервые строки train:")
    print(train_labels.head().to_string(index=False))


def print_baselines(test_labels: pd.DataFrame) -> None:
    """Посчитать MAE простых базовых прогнозов на test."""

    target = test_labels["target_delay_s"]

    zero_prediction = pd.Series(
        0.0,
        index=test_labels.index,
    )

    zero_mae = mean_absolute_error(
        target,
        zero_prediction,
    )

    current_deviation_mae = mean_absolute_error(
        target,
        test_labels["cur_dev_s"],
    )

    print("\n=== BASELINE ===")
    print(f"Нулевой прогноз MAE: {zero_mae:.2f} сек")
    print(
        f"cur_dev_s MAE:       "
        f"{current_deviation_mae:.2f} сек"
    )


def print_horizon_stats(test_labels: pd.DataFrame) -> None:
    """Проверить, что горизонт прогноза находится в диапазоне 10–15 минут."""

    times = test_labels[
        ["T", "target_time_begin"]
    ].copy()

    times["T"] = pd.to_datetime(times["T"])

    times["target_time_begin"] = pd.to_datetime(
        times["target_time_begin"]
    )

    horizon_min = (
        times["target_time_begin"] - times["T"]
    ).dt.total_seconds() / 60.0

    print("\n=== ГОРИЗОНТ ПРОГНОЗА ===")
    print(horizon_min.describe().to_string())

    print("\nУникальные значения горизонта:")

    print(
        ", ".join(
            f"{value:g}"
            for value in sorted(horizon_min.unique())
        )
    )

    outside_required_horizon = (
        (horizon_min < 10)
        | (horizon_min > 15)
    ).sum()

    print(
        "\nТочек вне диапазона 10–15 минут:",
        outside_required_horizon,
    )


def print_target_stats(test_labels: pd.DataFrame) -> None:
    """Вывести статистику целевой задержки."""

    target = test_labels["target_delay_s"]

    print("\n=== TARGET ===")
    print(target.describe().to_string())

    if "target_class" in test_labels.columns:
        print("\nКлассы target:")

        print(
            test_labels["target_class"]
            .value_counts()
            .to_string()
        )


def main() -> None:
    train_labels, test_labels, validate_points = load_data()

    print_dataset_info(
        train_labels,
        test_labels,
        validate_points,
    )

    print_baselines(test_labels)
    print_horizon_stats(test_labels)
    print_target_stats(test_labels)


if __name__ == "__main__":
    main()