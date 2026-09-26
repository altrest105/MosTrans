from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]

TRAFFIC_PATH = (
    PROJECT_ROOT
    / "ml"
    / "dataset"
    / "validate"
    / "traffic.csv"
)


class VehicleRegistry:
    """Связать ID бортового терминала NDTP с ID транспортного средства."""

    def __init__(
        self,
        traffic_path: Path = TRAFFIC_PATH,
    ) -> None:
        self._unit_to_tr: dict[int, int] = {}

        self._load(
            traffic_path
        )

    def _load(
        self,
        traffic_path: Path,
    ) -> None:
        """Загрузить соответствия unit_id → tr_id из телеметрии."""

        if not traffic_path.exists():
            raise FileNotFoundError(
                f"Файл телеметрии не найден: {traffic_path}"
            )

        traffic = pd.read_csv(
            traffic_path,
            usecols=[
                "unit_id",
                "tr_id",
            ],
            low_memory=False,
        )

        traffic = (
            traffic
            .dropna()
            .drop_duplicates()
        )

        for unit_id, group in traffic.groupby("unit_id"):
            tr_ids = group[
                "tr_id"
            ].unique()

            if len(tr_ids) != 1:
                raise RuntimeError(
                    f"Для unit_id={unit_id} найдено "
                    f"несколько tr_id: {tr_ids.tolist()}"
                )

            self._unit_to_tr[
                int(unit_id)
            ] = int(tr_ids[0])

    def get_tr_id(
        self,
        unit_id: int,
    ) -> int | None:
        """Получить tr_id по unit_id."""

        return self._unit_to_tr.get(
            unit_id
        )

    def contains(
        self,
        unit_id: int,
    ) -> bool:
        """Проверить наличие устройства в реестре."""

        return unit_id in self._unit_to_tr

    def __len__(self) -> int:
        """Получить количество известных устройств."""

        return len(
            self._unit_to_tr
        )