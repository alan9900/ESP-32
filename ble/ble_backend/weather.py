"""Open-Meteo current weather with a small, independent in-memory cache."""
from __future__ import annotations

import json
import math
import os
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

# Open-Meteo Geocoding: Changsha, Hunan, China (id 1815577).
DEFAULT_CITY = "Changsha"
DEFAULT_LATITUDE = 28.19874
DEFAULT_LONGITUDE = 112.97087
WEATHER_ENDPOINT = "https://api.open-meteo.com/v1/forecast"
DISPLAY_TIMEZONE = timezone(timedelta(hours=8))


def optional_number(value, minimum=None, maximum=None):
    """Reject absent, non-finite, boolean and out-of-range optional fields."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    if (minimum is not None and value < minimum) or (maximum is not None and value > maximum):
        return None
    return value


def condition_from_wmo(code):
    """Map Open-Meteo's WMO codes to the display's stable ASCII labels."""
    if isinstance(code, bool) or not isinstance(code, int):
        raise ValueError("invalid weather code")
    if code in (0, 1):
        return "Clear"
    if code in (2, 3):
        return "Cloudy"
    if code in (45, 48):
        return "Fog"
    if code in (51, 53, 55, 56, 57):
        return "Drizzle"
    if code in (61, 63, 65, 66, 67, 80, 81, 82):
        return "Rain"
    if code in (71, 73, 75, 77, 85, 86):
        return "Snow"
    if code in (95, 96, 97, 99):
        return "Thunder"
    return "Unknown"


def location_from_env():
    """Use the selected Changsha default; overrides must be unambiguous."""
    city = os.environ.get("DESK_WEATHER_CITY", "").strip()
    lat = os.environ.get("DESK_WEATHER_LAT", "").strip()
    lon = os.environ.get("DESK_WEATHER_LON", "").strip()
    if not lat and not lon:
        if city and city.casefold() not in ("changsha", "长沙", "长沙市"):
            raise ValueError("Set weather city, latitude and longitude together")
        return DEFAULT_CITY, DEFAULT_LATITUDE, DEFAULT_LONGITUDE
    if not lat or not lon:
        raise ValueError("Set both weather latitude and longitude")
    try:
        latitude, longitude = float(lat), float(lon)
    except ValueError:
        raise ValueError("Invalid weather latitude or longitude") from None
    if not math.isfinite(latitude) or not math.isfinite(longitude) or not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError("Invalid weather latitude or longitude")
    if len(city) > 48:
        raise ValueError("Weather city name too long")
    return city or "Custom", latitude, longitude


def read_weather(location):
    city, latitude, longitude = location
    query = urlencode({"latitude": latitude, "longitude": longitude,
                       "current": "temperature_2m,weather_code,relative_humidity_2m",
                       "daily": "temperature_2m_max,temperature_2m_min",
                       "forecast_days": 1,
                       "timeformat": "unixtime", "timezone": "Asia/Shanghai"})
    request = Request(WEATHER_ENDPOINT + "?" + query, headers={"Accept": "application/json", "User-Agent": "DeskUsageDisplay/1.0"})
    try:
        with urlopen(request, timeout=10) as response:
            data = json.load(response)
        current = data["current"]
        temperature = current["temperature_2m"]
        if isinstance(temperature, bool) or not isinstance(temperature, (int, float)) or not math.isfinite(temperature):
            raise ValueError("invalid temperature")
        timestamp = current["time"]
        if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)) or not math.isfinite(timestamp):
            raise ValueError("invalid timestamp")
        updated_at = datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec="seconds")
        # The screen uses Beijing time. Validate the forecast date, rather than
        # assuming that the first returned day is the current local day.
        forecast_date = None
        high_c = low_c = None
        daily = data.get("daily")
        if not isinstance(daily, dict):
            daily = {}
        daily_times = daily.get("time") or []
        highs = daily.get("temperature_2m_max") or []
        lows = daily.get("temperature_2m_min") or []
        if isinstance(daily_times, list) and daily_times:
            day_timestamp = optional_number(daily_times[0])
            if day_timestamp is not None:
                try:
                    day = datetime.fromtimestamp(day_timestamp, DISPLAY_TIMEZONE).date()
                except (OverflowError, OSError, ValueError):
                    day = None
                if day == datetime.now(DISPLAY_TIMEZONE).date():
                    forecast_date = day.isoformat()
                    high_c = optional_number(highs[0]) if isinstance(highs, list) and highs else None
                    low_c = optional_number(lows[0]) if isinstance(lows, list) and lows else None
        return {"city": city, "condition": condition_from_wmo(current["weather_code"]),
                "temperature_c": temperature,
                "humidity_percent": optional_number(current.get("relative_humidity_2m"), 0, 100),
                "high_c": high_c, "low_c": low_c, "forecast_date": forecast_date,
                "updated_at": updated_at, "error": None}
    except Exception:
        # Avoid exposing internal request URLs or exception contents in the response.
        raise RuntimeError("Weather request failed") from None


def unavailable(city=None, message="Weather unavailable"):
    return {"city": city, "condition": None, "temperature_c": None,
            "humidity_percent": None, "high_c": None, "low_c": None,
            "forecast_date": None, "updated_at": None, "error": message}


class WeatherCache:
    """Weather has its own timestamp and TTL, independent of account refreshes."""
    def __init__(self, success_ttl=900, retry_ttl=120):
        self.success_ttl = success_ttl
        self.retry_ttl = retry_ttl
        self.next_attempt = 0.0
        self.value = None
        self.location = None

    def get(self):
        now = time.monotonic()
        today = datetime.now(DISPLAY_TIMEZONE).date().isoformat()
        cached_day = self.value.get("forecast_date") if self.value is not None else None
        if self.value is not None and now < self.next_attempt and (not cached_day or cached_day == today):
            return self.value.copy()
        try:
            location = location_from_env()
        except ValueError as exc:
            self.value = unavailable(message=str(exc))
            self.next_attempt = now + self.retry_ttl
            return self.value.copy()
        try:
            self.value = read_weather(location)
            self.location = location
            self.next_attempt = now + self.success_ttl
        except RuntimeError:
            if self.value and self.value.get("temperature_c") is not None and self.location == location:
                # A failed refresh keeps the original observation timestamp, never a fake fresh time.
                self.value = {**self.value, "error": "Weather request failed"}
                if self.value.get("forecast_date") and self.value["forecast_date"] != today:
                    # Never relabel yesterday's daily extremes as today's.
                    self.value.update(high_c=None, low_c=None, forecast_date=None)
            else:
                self.value = unavailable(location[0], "Weather request failed")
            self.next_attempt = now + self.retry_ttl
        return self.value.copy()
