import asyncio
import logging
from collections.abc import Callable

from backend.ndtp.parser import (
    PACKET_CONN_REQUEST,
    SERVICE_GENERIC,
    TelemetryEvent,
    get_frame_size,
    parse_frame,
)

logger = logging.getLogger(__name__)


class NDTPReceiver:
    """TCP-сервер для приёма потока NDTP."""

    def __init__(
        self,
        host: str,
        port: int,
        on_telemetry: Callable[[TelemetryEvent], None],
    ) -> None:
        self._host = host
        self._port = port
        self._on_telemetry = on_telemetry
        self._server: asyncio.AbstractServer | None = None

    @property
    def running(self) -> bool:
        """Запущен ли TCP-сервер NDTP."""

        return self._server is not None

    async def start(self) -> None:
        """Запустить TCP-сервер."""

        self._server = await asyncio.start_server(
            self._handle_client,
            self._host,
            self._port,
        )
        logger.info(
            "NDTP-сервер запущен на %s:%d",
            self._host,
            self._port,
        )

    async def stop(self) -> None:
        """Остановить TCP-сервер."""

        if self._server is None:
            return

        self._server.close()
        await self._server.wait_closed()
        self._server = None
        logger.info("NDTP-сервер остановлен")

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        peer = writer.get_extra_info("peername")
        logger.info("NDTP-клиент подключился: %s", peer)

        buffer = bytearray()

        try:
            while True:
                chunk = await reader.read(4096)
                if not chunk:
                    break

                buffer.extend(chunk)

                while True:
                    try:
                        frame_size = get_frame_size(buffer)
                    except ValueError as exc:
                        logger.warning("Некорректный NDTP-поток: %s", exc)
                        return

                    if frame_size is None or len(buffer) < frame_size:
                        break

                    frame = bytes(buffer[:frame_size])
                    del buffer[:frame_size]

                    self._handle_frame(frame)

        except (ConnectionError, asyncio.IncompleteReadError) as exc:
            logger.warning("NDTP-соединение оборвано %s: %s", peer, exc)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass
            logger.info("NDTP-клиент отключился: %s", peer)

    def _handle_frame(self, frame: bytes) -> None:
        try:
            header, telemetry = parse_frame(frame)
        except (ValueError, OverflowError) as exc:
            logger.warning("Ошибка парсинга NDTP: %s", exc)
            return

        if (
            header.service_id == SERVICE_GENERIC
            and header.packet_type == PACKET_CONN_REQUEST
        ):
            logger.info(
                "NDTP handshake | unit_id=%d | request_id=%d",
                header.peer_address,
                header.request_id,
            )

        if telemetry is None:
            return

        self._on_telemetry(telemetry)

        logger.info(
            "Телеметрия | unit_id=%d | time=%s | lat=%.6f | lon=%.6f | "
            "speed=%.1f | heading=%.1f | valid=%s",
            telemetry.unit_id,
            telemetry.event_time.isoformat(),
            telemetry.lat,
            telemetry.lon,
            telemetry.speed,
            telemetry.heading,
            telemetry.location_valid,
        )
