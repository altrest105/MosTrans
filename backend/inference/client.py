import os

import httpx


DEFAULT_ML_SERVICE_URL = "http://127.0.0.1:8001"


class MLServiceClient:
    """HTTP-клиент для обращения Backend к ML-сервису."""

    def __init__(
        self,
        base_url: str | None = None,
    ) -> None:
        self._base_url = (
            base_url
            or os.getenv(
                "ML_SERVICE_URL",
                DEFAULT_ML_SERVICE_URL,
            )
        )

        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=2.0,
        )

    async def close(self) -> None:
        """Закрыть HTTP-клиент."""

        await self._client.aclose()

    async def health(self) -> dict:
        """Проверить доступность ML-сервиса."""

        response = await self._client.get(
            "/health"
        )

        response.raise_for_status()

        return response.json()

    async def predict(
        self,
        features: dict,
    ) -> dict:
        """Получить прогноз задержки."""

        response = await self._client.post(
            "/predict",
            json=features,
        )

        response.raise_for_status()

        return response.json()