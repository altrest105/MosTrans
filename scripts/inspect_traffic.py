import math
from pathlib import Path

import pandas as pd


DATA_DIR = Path("dataset")

# Какую прогнозную точку анализируем.
SAMPLE_INDEX = 0

# Размер временного окна перед моментом прогноза.
HISTORY_WINDOW_MINUTES = 10


def load_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
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

    labels["T"] = pd.to_datetime(labels["T"])

    labels["target_time_begin"] = pd.to_datetime(
        labels["target_time_begin"]
    )

    traffic["event_time"] = pd.to_datetime(
        traffic["event_time"]
    )

    return labels, traffic, schedule


def parse_point(value: str) -> tuple[float, float]:
    """
    Преобразовать строку WKT POINT в координаты.

    Пример:
    POINT (37.70782708 55.68567388)
    -> (37.70782708, 55.68567388)
    """

    value = (
        value
        .removeprefix("POINT (")
        .removesuffix(")")
    )

    lon, lat = value.split()

    return float(lon), float(lat)


def haversine_m(
    lon1: float,
    lat1: float,
    lon2: float,
    lat2: float,
) -> float:
    """Посчитать расстояние между двумя GPS-точками в метрах."""

    radius = 6_371_000

    lon1 = math.radians(lon1)
    lat1 = math.radians(lat1)
    lon2 = math.radians(lon2)
    lat2 = math.radians(lat2)

    dlon = lon2 - lon1
    dlat = lat2 - lat1

    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1)
        * math.cos(lat2)
        * math.sin(dlon / 2) ** 2
    )

    c = 2 * math.asin(math.sqrt(a))

    return radius * c


def print_traffic_info(traffic: pd.DataFrame) -> None:
    """Вывести общую информацию о таблице телеметрии."""

    print("=== ТЕЛЕМЕТРИЯ ===")
    print(f"Размер: {traffic.shape}")

    print("\nКолонки:")
    print(", ".join(traffic.columns))

    print("\nТипы данных:")
    print(traffic.dtypes.to_string())


def get_vehicle_history(
    traffic: pd.DataFrame,
    tr_id: int,
    prediction_time: pd.Timestamp,
) -> pd.DataFrame:
    """
    Получить историю ТС, доступную на момент прогноза.

    Телеметрия после prediction_time намеренно исключается,
    чтобы не использовать данные из будущего.
    """

    history = traffic[
        (traffic["tr_id"] == tr_id)
        & (traffic["event_time"] <= prediction_time)
    ].copy()

    return history.sort_values("event_time")


def get_valid_gps(history: pd.DataFrame) -> pd.DataFrame:
    """Оставить только телеметрию с валидными GPS-координатами."""

    return history[
        history["location_valid"]
        & history["lat"].notna()
        & history["lon"].notna()
    ].copy()


def print_history_info(
    history: pd.DataFrame,
    valid: pd.DataFrame,
    prediction_time: pd.Timestamp,
) -> None:
    """Вывести статистику истории ТС перед прогнозом."""

    print("\n=== ИСТОРИЯ ТС ===")
    print(f"Всего пакетов до T: {len(history)}")
    print(f"Валидных GPS-пакетов: {len(valid)}")

    if history.empty:
        print("История телеметрии отсутствует.")
        return

    print(
        "Период:",
        history["event_time"].min(),
        "->",
        history["event_time"].max(),
    )

    window_start = (
        prediction_time
        - pd.Timedelta(minutes=HISTORY_WINDOW_MINUTES)
    )

    last_window = valid[
        valid["event_time"] >= window_start
    ].copy()

    print(
        f"\nВалидных GPS-точек за последние "
        f"{HISTORY_WINDOW_MINUTES} минут: "
        f"{len(last_window)}"
    )

    if last_window.empty:
        print("Свежей GPS-телеметрии нет.")
        return

    print("\nПоследние 15 пакетов:")

    print(
        last_window[
            [
                "event_time",
                "speed",
                "lon",
                "lat",
                "heading",
            ]
        ]
        .tail(15)
        .to_string(index=False)
    )

    print("\nСтатистика скорости:")
    print(
        last_window["speed"]
        .describe()
        .to_string()
    )

    stopped_share = (
        last_window["speed"] <= 1
    ).mean()

    last_point = last_window.iloc[-1]

    telemetry_age_s = (
        prediction_time
        - last_point["event_time"]
    ).total_seconds()

    print(
        f"\nДоля пакетов со скоростью <= 1 км/ч: "
        f"{stopped_share:.3f}"
    )

    print(
        f"Последняя известная скорость: "
        f"{last_point['speed']:.1f} км/ч"
    )

    print(
        f"Возраст последней телеметрии: "
        f"{telemetry_age_s:.1f} сек"
    )


def print_target_info(
    sample: pd.Series,
    schedule: pd.DataFrame,
    valid: pd.DataFrame,
) -> None:
    """Вывести информацию о целевой остановке и расстоянии до неё."""

    target_rows = schedule[
        (schedule["tr_id"] == sample["tr_id"])
        & (
            schedule["tt_action_item_id"]
            == sample["target_stop_id"]
        )
    ]

    assert len(target_rows) == 1, (
        "Для целевой остановки ожидалась ровно одна строка "
        f"расписания, получено: {len(target_rows)}"
    )

    target = target_rows.iloc[0]

    target_lon, target_lat = parse_point(
        target["geom"]
    )

    print("\n=== ЦЕЛЕВАЯ ОСТАНОВКА ===")
    print(f"ID: {sample['target_stop_id']}")
    print(f"Плановое время: {target['time_begin']}")
    print(
        f"Координаты: "
        f"{target_lon:.6f}, {target_lat:.6f}"
    )
    print(f"Адрес: {target['building_address']}")

    horizon_seconds = (
        sample["target_time_begin"]
        - sample["T"]
    ).total_seconds()

    print(
        f"До планового прибытия: "
        f"{horizon_seconds:.0f} сек "
        f"({horizon_seconds / 60:.1f} мин)"
    )

    if valid.empty:
        print(
            "Расстояние до остановки определить нельзя: "
            "нет валидных GPS-точек."
        )
        return

    last_point = valid.iloc[-1]

    distance_to_target = haversine_m(
        last_point["lon"],
        last_point["lat"],
        target_lon,
        target_lat,
    )

    print(
        f"Расстояние от последней GPS-точки "
        f"до остановки: {distance_to_target:.1f} м"
    )


def main() -> None:
    labels, traffic, schedule = load_data()

    print_traffic_info(traffic)

    sample = labels.iloc[SAMPLE_INDEX]

    tr_id = int(sample["tr_id"])
    prediction_time = sample["T"]

    print("\n=== ПРОГНОЗНАЯ ТОЧКА ===")
    print(f"Sample ID: {sample['sample_id']}")
    print(f"ТС: {tr_id}")
    print(f"Момент прогноза T: {prediction_time}")
    print(f"Текущее отклонение: {sample['cur_dev_s']} сек")
    print(f"Целевая остановка: {sample['target_stop_id']}")

    history = get_vehicle_history(
        traffic=traffic,
        tr_id=tr_id,
        prediction_time=prediction_time,
    )

    valid = get_valid_gps(history)

    print_history_info(
        history=history,
        valid=valid,
        prediction_time=prediction_time,
    )

    print_target_info(
        sample=sample,
        schedule=schedule,
        valid=valid,
    )


if __name__ == "__main__":
    main()