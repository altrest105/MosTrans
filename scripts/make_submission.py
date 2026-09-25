from pathlib import Path

import pandas as pd
from catboost import CatBoostRegressor

from src.features import build_features


DATA_DIR = Path("dataset")
MODEL_PATH = Path("artifacts/catboost_final.cbm")
OUTPUT_PATH = Path("submissions/submission_simple_catboost.csv")


def load_validate_data() -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    """Загрузить точки прогноза, телеметрию и расписание validate."""

    points = pd.read_csv(
        DATA_DIR / "validate" / "points.csv"
    )

    traffic = pd.read_csv(
        DATA_DIR / "validate" / "traffic.csv",
        low_memory=False,
    )

    schedule = pd.read_csv(
        DATA_DIR / "validate" / "schedule_plan.csv"
    )

    points["T"] = pd.to_datetime(
        points["T"]
    )

    points["target_time_begin"] = pd.to_datetime(
        points["target_time_begin"]
    )

    traffic["event_time"] = pd.to_datetime(
        traffic["event_time"]
    )

    return points, traffic, schedule


def build_validate_features(
    points: pd.DataFrame,
    traffic: pd.DataFrame,
    schedule: pd.DataFrame,
) -> pd.DataFrame:
    """Построить признаки для всех прогнозных точек validate."""

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

    total = len(points)

    for index, sample in points.iterrows():
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

        processed = index + 1

        if processed % 50 == 0 or processed == total:
            print(
                f"Построение признаков: "
                f"{processed}/{total}"
            )

    return pd.DataFrame(rows)


def load_model() -> CatBoostRegressor:
    """Загрузить обученную CatBoost-модель."""

    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            f"Модель не найдена: {MODEL_PATH}"
        )

    model = CatBoostRegressor()

    model.load_model(
        str(MODEL_PATH)
    )

    return model


def validate_feature_schema(
    model: CatBoostRegressor,
    features: pd.DataFrame,
) -> pd.DataFrame:
    """
    Проверить соответствие признаков схеме,
    с которой была обучена модель.
    """

    expected_features = list(
        model.feature_names_
    )

    missing = [
        column
        for column in expected_features
        if column not in features.columns
    ]

    extra = [
        column
        for column in features.columns
        if column not in expected_features
    ]

    if missing:
        raise RuntimeError(
            "Не хватает признаков: "
            f"{missing}"
        )

    if extra:
        print(
            "Предупреждение: найдены лишние признаки: "
            f"{extra}"
        )

    return features[
        expected_features
    ]


def make_submission(
    points: pd.DataFrame,
    predictions,
) -> pd.DataFrame:
    """Сформировать и проверить итоговый submission."""

    submission = pd.DataFrame(
        {
            "sample_id": points["sample_id"],
            "prediction": predictions,
        }
    )

    if len(submission) != len(points):
        raise RuntimeError(
            "Количество прогнозов не совпадает "
            "с количеством точек validate."
        )

    if not submission["sample_id"].is_unique:
        raise RuntimeError(
            "В submission найдены дубли sample_id."
        )

    if submission["prediction"].isna().any():
        raise RuntimeError(
            "В submission найдены пропущенные прогнозы."
        )

    return submission


def save_submission(
    submission: pd.DataFrame,
) -> None:
    """Сохранить submission в формате, требуемом платформой."""

    OUTPUT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    submission.to_csv(
        OUTPUT_PATH,
        sep=";",
        index=False,
    )

    print(
        f"\nSubmission сохранён: {OUTPUT_PATH}"
    )

    print(
        f"Количество строк: {len(submission)}"
    )


def main() -> None:
    print("Загрузка модели...")
    model = load_model()

    print("Загрузка validate-данных...")
    points, traffic, schedule = load_validate_data()

    print("Построение признаков...")
    features = build_validate_features(
        points=points,
        traffic=traffic,
        schedule=schedule,
    )

    print(
        f"\nРазмер матрицы признаков: "
        f"{features.shape}"
    )

    print("\nПризнаки:")
    print(
        ", ".join(features.columns)
    )

    features = validate_feature_schema(
        model=model,
        features=features,
    )

    print("\nРасчёт прогнозов...")

    predictions = model.predict(
        features
    )

    submission = make_submission(
        points=points,
        predictions=predictions,
    )

    print("\nСтатистика прогнозов:")
    print(
        submission["prediction"]
        .describe()
        .to_string()
    )

    save_submission(
        submission
    )


if __name__ == "__main__":
    main()