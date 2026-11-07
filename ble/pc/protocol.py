"""BLE framing and display-only payload construction; no I/O at import time."""
from __future__ import annotations

import json
import math
import re
import struct
import zlib
from datetime import date, datetime, timezone

SERVICE_UUID = "8bf540f4-54ca-49cf-b7e5-e191b62a0001"
WRITE_UUID = "8bf540f4-54ca-49cf-b7e5-e191b62a0002"
STATUS_UUID = "8bf540f4-54ca-49cf-b7e5-e191b62a0003"
MAX_PAYLOAD = 4096
FRAME_MAX = 20
DATA_MAX = FRAME_MAX - 3
CONDITIONS = frozenset({"Clear", "Cloudy", "Fog", "Drizzle", "Rain", "Snow", "Thunder", "Unknown"})


def _object(value):
    return value if isinstance(value, dict) else {}


def _num(value, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    if (minimum is not None and value < minimum) or (maximum is not None and value > maximum):
        return None
    return value


def _time(value):
    if not isinstance(value, str) or len(value) > 35:
        return None
    try:
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if value.tzinfo is None or value.utcoffset() is None:
            return None
        return value.isoformat(timespec="seconds")
    except (ValueError, OverflowError):
        return None


def _date(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def _error(value):
    # Do not transfer arbitrary exceptions, paths or private data.
    return None if value is None else "unavailable"


def make_payload(snapshot, now=None):
    """Build a display-only object. Timestamps for source data are not refreshed."""
    if not isinstance(snapshot, dict) or snapshot.get("mode") not in ("live", "mock"):
        raise ValueError("Invalid snapshot")
    updated = _time(snapshot.get("updated_at"))
    if updated is None:
        raise ValueError("Snapshot timestamp missing")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Host time must include a timezone")

    codex, weather = (_object(snapshot.get(k)) for k in ("codex", "weather"))

    def window(item):
        item = _object(item)
        return {"remaining_percent": _num(item.get("remaining_percent"), 0, 100),
                "resets_at": _time(item.get("resets_at"))}

    city = weather.get("city")
    city = city if isinstance(city, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9 ._-]{0,47}", city) else None
    condition = weather.get("condition")
    condition = condition if isinstance(condition, str) and condition in CONDITIONS else None
    data = {
        "mode": snapshot["mode"], "updated_at": updated,
        "host_utc": now.astimezone(timezone.utc).isoformat(timespec="seconds"),
        "codex": {"five_hour": window(codex.get("five_hour")), "weekly": window(codex.get("weekly")),
                  "error": _error(codex.get("error"))},
        "weather": {"city": city, "condition": condition, "temperature_c": _num(weather.get("temperature_c"), -100, 100),
                    "humidity_percent": _num(weather.get("humidity_percent"), 0, 100),
                    "high_c": _num(weather.get("high_c"), -100, 100), "low_c": _num(weather.get("low_c"), -100, 100),
                    "forecast_date": _date(weather.get("forecast_date")), "updated_at": _time(weather.get("updated_at")),
                    "error": _error(weather.get("error"))},
    }
    encoded = json.dumps(data, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode("utf-8")
    if not 0 < len(encoded) <= MAX_PAYLOAD:
        raise ValueError("Invalid encoded length")
    return encoded


def frames(payload):
    """Frames fit a default 23-byte ATT MTU, using write-with-response."""
    if not isinstance(payload, bytes) or not 0 < len(payload) <= MAX_PAYLOAD:
        raise ValueError("Invalid payload size")
    yield b"\x01" + struct.pack("<HI", len(payload), zlib.crc32(payload) & 0xFFFFFFFF)
    for sequence, offset in enumerate(range(0, len(payload), DATA_MAX)):
        yield b"\x02" + struct.pack("<H", sequence) + payload[offset:offset + DATA_MAX]
    yield b"\x03"
