from pathlib import Path
import logging

import pandas as pd

logger = logging.getLogger(__name__)


class VehicleRegistry:
    """Опциональное соответствие unit_id → tr_id из предоставленного датасета."""

    def __init__(self, traffic_path: Path) -> None:
        self._unit_to_tr: dict[int, int] = {}

        if not traffic_path.exists():
            logger.warning(
                "Файл registry не найден: %s. Работаем без tr_id.",
                traffic_path,
            )
            return

        data = pd.read_csv(
            traffic_path,
            usecols=["unit_id", "tr_id"],
        ).dropna()

        for unit_id, group in data.groupby("unit_id"):
            tr_ids = group["tr_id"].astype(int).unique()
            if len(tr_ids) == 1:
                self._unit_to_tr[int(unit_id)] = int(tr_ids[0])

        logger.info(
            "Загружено соответствий unit_id → tr_id: %d",
            len(self._unit_to_tr),
        )

    def get_tr_id(self, unit_id: int) -> int | None:
        return self._unit_to_tr.get(int(unit_id))

    def __len__(self) -> int:
        return len(self._unit_to_tr)
