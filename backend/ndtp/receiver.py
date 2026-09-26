import asyncio
import logging
from collections.abc import Callable
from backend.ndtp.parser import TelemetryEvent

from backend.ndtp.parser import (
    SERVICE_GENERIC_CONTROLS,
    SERVICE_NAVDATA,
    TYPE_CONN_REQUEST,
    TYPE_REALTIME,
    get_frame_size,
    parse_frame,
)


logger = logging.getLogger(__name__)


class NDTPReceiver:
    """TCP-сервер для приёма телематических пакетов NDTP."""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 9201,
        on_telemetry: Callable[
            [TelemetryEvent],
            None,
        ] | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.on_telemetry = on_telemetry

        self.server: asyncio.Server | None = None

    async def start(self) -> None:
        """Запустить TCP-сервер."""

        self.server = await asyncio.start_server(
            self.handle_client,
            host=self.host,
            port=self.port,
        )

        logger.info(
            "NDTP-сервер запущен на %s:%d",
            self.host,
            self.port,
        )

    async def stop(self) -> None:
        """Корректно остановить TCP-сервер."""

        if self.server is None:
            return

        self.server.close()
        await self.server.wait_closed()

        logger.info(
            "NDTP-сервер остановлен"
        )

    async def handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Обработать TCP-соединение одного устройства."""

        peer = writer.get_extra_info(
            "peername"
        )

        logger.info(
            "NDTP-клиент подключился: %s",
            peer,
        )

        buffer = bytearray()

        try:
            while True:
                chunk = await reader.read(
                    4096
                )

                if not chunk:
                    break

                buffer.extend(
                    chunk
                )

                while True:
                    frame_size = get_frame_size(
                        buffer
                    )

                    if frame_size is None:
                        break

                    if len(buffer) < frame_size:
                        break

                    frame = bytes(
                        buffer[:frame_size]
                    )

                    del buffer[:frame_size]

                    self.handle_frame(
                        frame
                    )

        except (
            ConnectionError,
            asyncio.IncompleteReadError,
        ):
            logger.warning(
                "Соединение потеряно: %s",
                peer,
            )

        except Exception:
            logger.exception(
                "Ошибка обработки NDTP: %s",
                peer,
            )

        finally:
            writer.close()

            try:
                await writer.wait_closed()
            except ConnectionError:
                pass

            logger.info(
                "NDTP-клиент отключился: %s",
                peer,
            )

    def handle_frame(
        self,
        frame: bytes,
    ) -> None:
        """Обработать один полный NDTP-кадр."""

        header, telemetry = parse_frame(
            frame
        )

        if (
            header.service_id
            == SERVICE_GENERIC_CONTROLS
            and header.packet_type
            == TYPE_CONN_REQUEST
        ):
            logger.info(
                "NDTP handshake | "
                "unit_id=%d | request_id=%d",
                header.peer_address,
                header.request_id,
            )

            return

        if (
            header.service_id
            == SERVICE_NAVDATA
            and header.packet_type
            == TYPE_REALTIME
        ):
            if telemetry is None:
                logger.warning(
                    "Realtime-пакет без "
                    "G6CellNav00 | unit_id=%d",
                    header.peer_address,
                )

                return

            logger.info(
                "Телеметрия | "
                "unit_id=%d | "
                "time=%s | "
                "lat=%.6f | "
                "lon=%.6f | "
                "speed=%.1f | "
                "heading=%.1f | "
                "valid=%s",
                telemetry.unit_id,
                telemetry.event_time.isoformat(),
                telemetry.lat,
                telemetry.lon,
                telemetry.speed,
                telemetry.heading,
                telemetry.location_valid,
            )

            if self.on_telemetry is not None:
                self.on_telemetry(
                    telemetry
                )

            return

        logger.debug(
            "Неизвестный пакет | "
            "unit=%d service=%d type=%d",
            header.peer_address,
            header.service_id,
            header.packet_type,
        )