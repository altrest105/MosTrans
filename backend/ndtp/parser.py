from dataclasses import dataclass
from datetime import datetime, timezone
import struct

NPL_HEADER_SIZE = 15
NPH_HEADER_SIZE = 10

NPL_SIGNATURE = 0x7E7E
NPL_TYPE_NPH = 0x02

SERVICE_GENERIC = 0
SERVICE_NAVDATA = 1
PACKET_CONN_REQUEST = 100
PACKET_REALTIME = 101

CELL_NAV00 = 0
NAV00_PAYLOAD_SIZE = 26


@dataclass(slots=True)
class NDTPHeader:
    """Основные поля заголовков NDTP."""

    peer_address: int
    service_id: int
    packet_type: int
    request_id: int


@dataclass(slots=True)
class TelemetryEvent:
    """Нормализованное событие навигационной телеметрии."""

    unit_id: int
    event_time: datetime
    lon: float
    lat: float
    alt: float
    speed: float
    heading: float
    location_valid: bool
    source_event_time: datetime | None = None


def get_frame_size(buffer: bytes | bytearray) -> int | None:
    """Получить полный размер NDTP-кадра из NPL-заголовка."""

    if len(buffer) < NPL_HEADER_SIZE:
        return None

    signature, data_size = struct.unpack_from("<HH", buffer, 0)

    if signature != NPL_SIGNATURE:
        raise ValueError(
            f"Некорректная сигнатура NDTP: 0x{signature:04X}"
        )

    return NPL_HEADER_SIZE + int(data_size)


def parse_headers(frame: bytes) -> NDTPHeader:
    """Распарсить NPL и NPH заголовки."""

    if len(frame) < NPL_HEADER_SIZE + NPH_HEADER_SIZE:
        raise ValueError("NDTP-кадр слишком короткий")

    (
        signature,
        data_size,
        _npl_flags,
        _crc,
        npl_type,
        peer_address,
        _npl_request_id,
    ) = struct.unpack_from("<HHHHBIH", frame, 0)

    if signature != NPL_SIGNATURE:
        raise ValueError("Некорректная сигнатура NDTP")

    if npl_type != NPL_TYPE_NPH:
        raise ValueError(f"Неподдерживаемый тип NPL: {npl_type}")

    expected_size = NPL_HEADER_SIZE + int(data_size)
    if len(frame) != expected_size:
        raise ValueError(
            f"Некорректный размер кадра: {len(frame)} != {expected_size}"
        )

    service_id, packet_type, _nph_flags, request_id = struct.unpack_from(
        "<HHHI", frame, NPL_HEADER_SIZE
    )

    return NDTPHeader(
        peer_address=int(peer_address),
        service_id=int(service_id),
        packet_type=int(packet_type),
        request_id=int(request_id),
    )


def parse_nav00(payload: bytes, unit_id: int) -> TelemetryEvent:
    """Распарсить payload ячейки G6CellNav00."""

    if len(payload) < NAV00_PAYLOAD_SIZE:
        raise ValueError("Недостаточный размер G6CellNav00")

    (
        timestamp,
        longitude_raw,
        latitude_raw,
        extra_dop,
        _bat_voltage,
        speed_avg,
        _speed_max,
        course,
        _track,
        altitude,
        _nsat,
        _pdop,
    ) = struct.unpack_from("<IIIBBHHHHHBB", payload, 0)

    lon = float(longitude_raw) / 10_000_000.0
    lat = float(latitude_raw) / 10_000_000.0

    if not (extra_dop & (1 << 6)):
        lon = -lon
    if not (extra_dop & (1 << 5)):
        lat = -lat

    location_valid = bool(extra_dop & (1 << 7))

    return TelemetryEvent(
        unit_id=int(unit_id),
        event_time=datetime.fromtimestamp(int(timestamp), tz=timezone.utc),
        lon=lon,
        lat=lat,
        alt=float(altitude),
        speed=float(speed_avg),
        heading=float(course),
        location_valid=location_valid,
    )


def parse_realtime(frame: bytes, header: NDTPHeader) -> TelemetryEvent | None:
    """Извлечь Nav00 из realtime-пакета."""

    body_offset = NPL_HEADER_SIZE + NPH_HEADER_SIZE
    body = frame[body_offset:]

    if len(body) < 2 + NAV00_PAYLOAD_SIZE:
        return None

    cell_type = body[0]
    if cell_type != CELL_NAV00:
        return None

    payload = body[2 : 2 + NAV00_PAYLOAD_SIZE]
    return parse_nav00(payload, header.peer_address)


def parse_frame(frame: bytes) -> tuple[NDTPHeader, TelemetryEvent | None]:
    """Распарсить один NDTP-кадр."""

    header = parse_headers(frame)

    if (
        header.service_id == SERVICE_NAVDATA
        and header.packet_type == PACKET_REALTIME
    ):
        return header, parse_realtime(frame, header)

    return header, None
