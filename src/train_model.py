import json
from pathlib import Path

import pandas as pd
from catboost import CatBoostRegressor
from sklearn.metrics import mean_absolute_error

from .features import FEATURE_NAMES, build_features


PROJECT_ROOT = Path(__file__).resolve().parents[1]

DATA_DIR = PROJECT_ROOT / "dataset"
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"

MODEL_PATH = ARTIFACTS_DIR / "catboost_final.cbm"
FEATURE_IMPORTANCE_PATH = (
    ARTIFACTS_DIR / "feature_importance.csv"
)
TEST_PREDICTIONS_PATH = (
    ARTIFACTS_DIR / "test_predictions.csv"
)
METRICS_PATH = ARTIFACTS_DIR / "metrics.json"


MODEL_PARAMS = {
    "iterations": 500,
    "depth": 8,
    "learning_rate": 0.05,
    "loss_function": "MAE",
    "eval_metric": "MAE",
    "random_seed": 42,
    "verbose": 100,
}


FORBIDDEN_FEATURES = {
    "target_delay_s",
    "target_class",
    "time_fact_begin",
}


def load_split(
    split_name: str,
    labels_filename: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Загрузить часть датасета и построить
    матрицу признаков для всех прогнозных точек.
    """

    labels = pd.read_csv(
        DATA_DIR / "labels" / labels_filename
    )

    traffic = pd.read_csv(
        DATA_DIR / split_name / "traffic.csv",
        low_memory=False,
    )

    schedule = pd.read_csv(
        DATA_DIR / split_name / "schedule.csv"
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

    return labels, build_feature_matrix(
        labels=labels,
        traffic=traffic,
        schedule=schedule,
        split_name=split_name,
    )


def build_feature_matrix(
    labels: pd.DataFrame,
    traffic: pd.DataFrame,
    schedule: pd.DataFrame,
    split_name: str,
) -> pd.DataFrame:
    """Построить матрицу признаков для одной части датасета."""

    # Группируем данные один раз, чтобы для каждой
    # прогнозной точки не сканировать весь датасет.
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

    for position, (_, sample) in enumerate(
        labels.iterrows(),
        start=1,
    ):
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

        rows.append(features)

        if position % 500 == 0 or position == total:
            print(
                f"{split_name}: "
                f"{position}/{total}"
            )

    return pd.DataFrame(
        rows,
        columns=FEATURE_NAMES,
    )


def validate_feature_matrix(
    features: pd.DataFrame,
) -> None:
    """
    Проверить схему признаков и убедиться,
    что в модель не попали целевые данные.
    """

    missing = [
        feature
        for feature in FEATURE_NAMES
        if feature not in features.columns
    ]

    if missing:
        raise RuntimeError(
            "Отсутствуют обязательные признаки: "
            f"{missing}"
        )

    leakage = (
        set(features.columns)
        & FORBIDDEN_FEATURES
    )

    if leakage:
        raise RuntimeError(
            "Обнаружена утечка целевых данных: "
            f"{sorted(leakage)}"
        )


def create_model() -> CatBoostRegressor:
    """Создать CatBoost-модель с зафиксированными параметрами."""

    return CatBoostRegressor(
        **MODEL_PARAMS
    )


def save_feature_importance(
    model: CatBoostRegressor,
    feature_names: list[str],
) -> pd.DataFrame:
    """Сохранить важность признаков обученной модели."""

    importance = pd.DataFrame(
        {
            "feature": feature_names,
            "importance": model.get_feature_importance(),
        }
    ).sort_values(
        "importance",
        ascending=False,
    )

    importance.to_csv(
        FEATURE_IMPORTANCE_PATH,
        index=False,
    )

    return importance


def build_test_diagnostics(
    test_labels: pd.DataFrame,
    predictions,
) -> pd.DataFrame:
    """Сформировать таблицу ошибок модели на test."""

    results = test_labels[
        [
            "sample_id",
            "tr_id",
            "T",
            "target_stop_id",
            "cur_dev_s",
            "target_delay_s",
            "target_class",
        ]
    ].copy()

    results["prediction"] = predictions

    results["model_error"] = (
        results["target_delay_s"]
        - results["prediction"]
    ).abs()

    results["baseline_error"] = (
        results["target_delay_s"]
        - results["cur_dev_s"]
    ).abs()

    results["gain_vs_baseline"] = (
        results["baseline_error"]
        - results["model_error"]
    )

    return results


def save_metrics(
    baseline_mae: float,
    model_mae: float,
    better_count: int,
    worse_count: int,
) -> None:
    """Сохранить основные метрики локальной проверки."""

    metrics = {
        "baseline_mae": float(baseline_mae),
        "catboost_test_mae": float(model_mae),
        "improvement_mae": float(
            baseline_mae - model_mae
        ),
        "model_better_count": int(better_count),
        "model_worse_count": int(worse_count),
    }

    with METRICS_PATH.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            metrics,
            file,
            ensure_ascii=False,
            indent=2,
        )


def main() -> None:
    ARTIFACTS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    print("=== ПОСТРОЕНИЕ ПРИЗНАКОВ ===")

    print("\nTrain:")
    train_labels, x_train = load_split(
        split_name="train",
        labels_filename="labels_train.csv",
    )

    print("\nTest:")
    test_labels, x_test = load_split(
        split_name="test",
        labels_filename="labels_test.csv",
    )

    validate_feature_matrix(
        x_train
    )

    validate_feature_matrix(
        x_test
    )

    print(
        f"\nРазмер train: {x_train.shape}"
    )

    print(
        f"Размер test:  {x_test.shape}"
    )

    print("\nПризнаки:")
    print(
        ", ".join(x_train.columns)
    )

    y_train = train_labels[
        "target_delay_s"
    ]

    y_test = test_labels[
        "target_delay_s"
    ]

    # Сравниваем модель с базовым прогнозом:
    # текущее отклонение принимается за будущее.
    baseline_predictions = test_labels[
        "cur_dev_s"
    ]

    baseline_mae = mean_absolute_error(
        y_test,
        baseline_predictions,
    )

    print("\n=== BASELINE ===")

    print(
        f"cur_dev_s MAE: "
        f"{baseline_mae:.3f} сек"
    )

    # Модель для локальной проверки обучается только
    # на train и оценивается на отдельном test.
    print("\n=== ЛОКАЛЬНАЯ ПРОВЕРКА CATBOOST ===")

    validation_model = create_model()

    validation_model.fit(
        x_train,
        y_train,
    )

    test_predictions = validation_model.predict(
        x_test
    )

    model_mae = mean_absolute_error(
        y_test,
        test_predictions,
    )

    improvement = (
        baseline_mae - model_mae
    )

    print(
        f"\nCatBoost test MAE: "
        f"{model_mae:.3f} сек"
    )

    print(
        f"Улучшение относительно baseline: "
        f"{improvement:.3f} сек"
    )

    # Сохраняем и выводим важность признаков.
    importance = save_feature_importance(
        model=validation_model,
        feature_names=list(x_train.columns),
    )

    print("\n=== ВАЖНОСТЬ ПРИЗНАКОВ ===")

    print(
        importance.to_string(
            index=False
        )
    )

    # Анализируем ошибки модели относительно baseline.
    diagnostics = build_test_diagnostics(
        test_labels=test_labels,
        predictions=test_predictions,
    )

    better_count = int(
        (
            diagnostics["gain_vs_baseline"] > 0
        ).sum()
    )

    worse_count = int(
        (
            diagnostics["gain_vs_baseline"] < 0
        ).sum()
    )

    print("\n=== МОДЕЛЬ ПРОТИВ BASELINE ===")
    print(f"Модель лучше: {better_count}")
    print(f"Модель хуже:  {worse_count}")

    diagnostics.to_csv(
        TEST_PREDICTIONS_PATH,
        index=False,
    )

    save_metrics(
        baseline_mae=baseline_mae,
        model_mae=model_mae,
        better_count=better_count,
        worse_count=worse_count,
    )

    # Для финальной модели используем всю доступную
    # размеченную выборку: train + test.
    print("\n=== ФИНАЛЬНАЯ МОДЕЛЬ ===")
    print("Обучение на train + test...")

    x_all = pd.concat(
        [
            x_train,
            x_test,
        ],
        ignore_index=True,
    )

    y_all = pd.concat(
        [
            y_train,
            y_test,
        ],
        ignore_index=True,
    )

    validate_feature_matrix(
        x_all
    )

    print(
        f"Размер X: {x_all.shape}"
    )

    print(
        f"Размер y: {y_all.shape}"
    )

    final_model = create_model()

    final_model.fit(
        x_all,
        y_all,
    )

    final_model.save_model(
        str(MODEL_PATH)
    )

    print(
        f"\nМодель сохранена: "
        f"{MODEL_PATH}"
    )

    print(
        f"Метрики сохранены: "
        f"{METRICS_PATH}"
    )

    print(
        f"Диагностика test сохранена: "
        f"{TEST_PREDICTIONS_PATH}"
    )

    print(
        "\nОбучение завершено."
    )


if __name__ == "__main__":
    main()