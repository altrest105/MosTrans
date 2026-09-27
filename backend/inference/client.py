import httpx


class MLServiceClient:
    """Асинхронный клиент отдельного ML-сервиса."""

    def __init__(self, base_url: str, timeout_s: float = 2.0) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_s,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def health(self) -> dict:
        response = await self._client.get("/health")
        response.raise_for_status()
        return response.json()

    async def predict(self, features: dict) -> dict:
        response = await self._client.post("/predict", json=features)
        response.raise_for_status()
        return response.json()
