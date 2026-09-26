import struct
from dataclasses import dataclass
from datetime import datetime, timezone


NPL_HEADER_SIZE = 15
NPH_HEADER_SIZE = 10

NDTP_SIGNATURE = 0x7E7E

SERVICE_GENERIC_CONTROLS = 0
SERVICE_NAVDATA = 1

TYPE_CONN_REQUEST = 100
TYPE_REALTIME = 101

CELL_NAV00 = 0
NAV00_PAYLOAD_SIZE = 26


@dataclass(slots=True)
class NDTPHeader:
    """Заголовки одного NDTP-пакета."""

    peer_address: int
    service_id: int
    packet_type: int
    request_id: int


@dataclass(slots=True)
class TelemetryEvent:
    """Нормализованная навигационная телеметрия ТС."""

    unit_id: int
    event_time: datetime

    lon: float
    lat: float
    alt: float

    speed: float
    heading: float

    location_valid: bool


def get_frame_size(buffer: bytes) -> int | None:
    """
    Определить полный размер первого NDTP-кадра в буфере.

    Возвращает None, если данных для чтения NPL-заголовка
    пока недостаточно.
    """

    if len(buffer) < NPL_HEADER_SIZE:
        return None

    signature, data_size = struct.unpack_from(
        "<HH",
        buffer,
        0,
    )

    if signature != NDTP_SIGNATURE:
        raise ValueError(
            f"Некорректная сигнатура NDTP: "
            f"0x{signature:04X}"
        )

    return NPL_HEADER_SIZE + data_size


def parse_headers(frame: bytes) -> NDTPHeader:
    """Разобрать заголовки NPL и NPH."""

    if len(frame) < NPL_HEADER_SIZE + NPH_HEADER_SIZE:
        raise ValueError(
            "NDTP-пакет слишком короткий."
        )

    (
        signature,
        data_size,
        _npl_flags,
        _crc,
        npl_type,
        peer_address,
        _npl_request_id,
    ) = struct.unpack_from(
        "<HHHHBIH",
        frame,
        0,
    )

    if signature != NDTP_SIGNATURE:
        raise ValueError(
            f"Некорректная сигнатура NDTP: "
            f"0x{signature:04X}"
        )

    if npl_type != 0x02:
        raise ValueError(
            f"Неожиданный тип NPL: {npl_type}"
        )

    expected_size = (
        NPL_HEADER_SIZE
        + data_size
    )

    if len(frame) != expected_size:
        raise ValueError(
            "Размер NDTP-пакета не совпадает "
            "со значением dataSize."
        )

    (
        service_id,
        packet_type,
        _nph_flags,
        request_id,
    ) = struct.unpack_from(
        "<HHHI",
        frame,
        NPL_HEADER_SIZE,
    )

    return NDTPHeader(
        peer_address=peer_address,
        service_id=service_id,
        packet_type=packet_type,
        request_id=request_id,
    )


def parse_nav00(
    payload: bytes,
    unit_id: int,
) -> TelemetryEvent:
    """Разобрать payload навигационной ячейки G6CellNav00."""

    if len(payload) < NAV00_PAYLOAD_SIZE:
        raise ValueError(
            "Недостаточно данных для G6CellNav00."
        )

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
    ) = struct.unpack_from(
        "<IIIBBHHHHHBB",
        payload,
        0,
    )

    # Бит 5 определяет знак широты:
    # 1 = север, 0 = юг.
    north = bool(
        extra_dop & (1 << 5)
    )

    # Бит 6 определяет знак долготы:
    # 1 = восток, 0 = запад.
    east = bool(
        extra_dop & (1 << 6)
    )

    # Бит 7 показывает достоверность координат.
    location_valid = bool(
        extra_dop & (1 << 7)
    )

    lat = latitude_raw / 10_000_000
    lon = longitude_raw / 10_000_000

    if not north:
        lat = -lat

    if not east:
        lon = -lon

    return TelemetryEvent(
        unit_id=unit_id,
        event_time=datetime.fromtimestamp(
            timestamp,
            tz=timezone.utc,
        ),
        lon=lon,
        lat=lat,
        alt=float(altitude),
        speed=float(speed_avg),
        heading=float(course),
        location_valid=location_valid,
    )


def parse_realtime(
    frame: bytes,
    header: NDTPHeader,
) -> TelemetryEvent | None:
    """
    Извлечь G6CellNav00 из realtime-пакета.

    Навигационная ячейка согласно спецификации
    всегда находится первой.
    """

    body_offset = (
        NPL_HEADER_SIZE
        + NPH_HEADER_SIZE
    )

    body = frame[
        body_offset:
    ]

    if len(body) < 2:
        return None

    cell_type = body[0]
    _cell_number = body[1]

    if cell_type != CELL_NAV00:
        return None

    nav_payload = body[
        2:
        2 + NAV00_PAYLOAD_SIZE
    ]

    return parse_nav00(
        payload=nav_payload,
        unit_id=header.peer_address,
    )


def parse_frame(
    frame: bytes,
) -> tuple[NDTPHeader, TelemetryEvent | None]:
    """Разобрать один полный NDTP-кадр."""

    header = parse_headers(
        frame
    )

    if (
        header.service_id == SERVICE_NAVDATA
        and header.packet_type == TYPE_REALTIME
    ):
        telemetry = parse_realtime(
            frame=frame,
            header=header,
        )

        return header, telemetry

    return header, None