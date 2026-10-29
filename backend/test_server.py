import json
import io
import os
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

import server
import weather


class ParseLimitsTests(unittest.TestCase):
    def test_exact_windows_and_missing_values(self):
        data = {"rateLimitsByLimitId": {"codex": {"primary": {"usedPercent": 27, "windowDurationMins": 300, "resetsAt": 1700000000}, "secondary": {"usedPercent": 80, "windowDurationMins": 10080, "resetsAt": 1700100000}}}}
        five, week = server.parse_limits(data)
        self.assertEqual(five["remaining_percent"], 73)
        self.assertEqual(week["remaining_percent"], 20)
        self.assertTrue(five["resets_at"].endswith("+00:00"))
        self.assertEqual(server.parse_limits({}), (server.empty_window(), server.empty_window()))

    def test_other_buckets_do_not_masquerade_as_codex(self):
        self.assertEqual(server.parse_limits({"rateLimits": {"limitId": "other", "primary": {"usedPercent": 4, "windowDurationMins": 300}}})[0], server.empty_window())

    def test_partial_failures_are_independent(self):
        with patch("server.read_codex", return_value=({"remaining_percent": 15, "resets_at": None}, server.empty_window())), patch("server.WeatherCache.get", return_value=weather.unavailable(message="test")):
            result = server.live_status()
        self.assertEqual(result["codex"]["five_hour"]["remaining_percent"], 15)
        self.assertNotIn("deepseek", result)


class HttpTests(unittest.TestCase):
    def test_status_requires_token_and_mock_is_labelled(self):
        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        httpd.state = server.State(True, 60)
        httpd.access_token = "example-token"
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        url = "http://127.0.0.1:%d/api/status" % httpd.server_port
        try:
            with self.assertRaises(HTTPError) as e:
                urlopen(url)
            self.assertEqual(e.exception.code, 401)
            with urlopen(Request(url, headers={"Authorization": "Bearer example-token"})) as response:
                data = json.load(response)
            self.assertEqual(data["mode"], "mock")
            self.assertNotIn("deepseek", data)
            self.assertEqual(data["weather"]["city"], "Changsha")
            self.assertEqual(data["weather"]["condition"], "Clear")
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join()


class WeatherTests(unittest.TestCase):
    def test_location_default_and_safe_override(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(weather.location_from_env(), ("Changsha", 28.19874, 112.97087))
        with patch.dict(os.environ, {"DESK_WEATHER_CITY": "Beijing"}, clear=True):
            with self.assertRaises(ValueError):
                weather.location_from_env()
        with patch.dict(os.environ, {"DESK_WEATHER_CITY": "Beijing", "DESK_WEATHER_LAT": "39.9", "DESK_WEATHER_LON": "116.4"}, clear=True):
            self.assertEqual(weather.location_from_env(), ("Beijing", 39.9, 116.4))
        with patch.dict(os.environ, {"DESK_WEATHER_LAT": "NaN", "DESK_WEATHER_LON": "116"}, clear=True):
            with self.assertRaises(ValueError):
                weather.location_from_env()

    def test_api_parses_model_timestamp_and_conditions(self):
        payload = {"current": {"time": 1700000000, "temperature_2m": 17.5, "weather_code": 63}}
        response = io.BytesIO(json.dumps(payload).encode())
        with patch("weather.urlopen", return_value=response) as request:
            data = weather.read_weather(("Changsha", 28.19874, 112.97087))
        self.assertEqual(data["condition"], "Rain")
        self.assertEqual(data["temperature_c"], 17.5)
        self.assertEqual(data["updated_at"], datetime.fromtimestamp(1700000000, timezone.utc).isoformat(timespec="seconds"))
        self.assertIn("timeformat=unixtime", request.call_args.args[0].full_url)
        self.assertEqual(weather.condition_from_wmo(95), "Thunder")
        self.assertEqual(weather.condition_from_wmo(999), "Unknown")

    def test_china_day_extremes_and_optional_humidity(self):
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 10, 28, 0, 5, tzinfo=weather.DISPLAY_TIMEZONE)

        midnight = datetime(2026, 10, 28, tzinfo=weather.DISPLAY_TIMEZONE)
        payload = {"current": {"time": midnight.timestamp() - 600, "temperature_2m": 17.5,
                               "weather_code": 63, "relative_humidity_2m": 68},
                   "daily": {"time": [midnight.timestamp()],
                             "temperature_2m_max": [24.5], "temperature_2m_min": [11.0]}}
        with patch("weather.datetime", Clock), patch("weather.urlopen", return_value=io.BytesIO(json.dumps(payload).encode())) as request:
            data = weather.read_weather(("Changsha", 28.19874, 112.97087))
        self.assertEqual((data["humidity_percent"], data["high_c"], data["low_c"]), (68, 24.5, 11.0))
        self.assertEqual(data["forecast_date"], "2026-10-28")
        self.assertIn("timezone=Asia%2FShanghai", request.call_args.args[0].full_url)
        self.assertIn("relative_humidity_2m", request.call_args.args[0].full_url)

        # A mismatched day and invalid humidity must not leak fabricated values.
        payload["daily"]["time"] = [(midnight - timedelta(days=1)).timestamp()]
        payload["current"]["relative_humidity_2m"] = 101
        with patch("weather.datetime", Clock), patch("weather.urlopen", return_value=io.BytesIO(json.dumps(payload).encode())):
            data = weather.read_weather(("Changsha", 28.19874, 112.97087))
        self.assertIsNone(data["humidity_percent"])
        self.assertIsNone(data["high_c"])
        self.assertIsNone(data["low_c"])
        self.assertEqual(data["temperature_c"], 17.5)

        payload["daily"] = ["malformed"]
        with patch("weather.datetime", Clock), patch("weather.urlopen", return_value=io.BytesIO(json.dumps(payload).encode())):
            data = weather.read_weather(("Changsha", 28.19874, 112.97087))
        self.assertIsNone(data["high_c"])
        self.assertEqual(data["temperature_c"], 17.5)

    def test_midnight_failed_refresh_clears_yesterdays_extremes(self):
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 10, 28, 0, 1, tzinfo=weather.DISPLAY_TIMEZONE)

        value = {"city": "Changsha", "condition": "Clear", "temperature_c": 20.0,
                 "humidity_percent": 70, "high_c": 27, "low_c": 19,
                 "forecast_date": "2026-10-27", "updated_at": "2026-10-27T15:45:00+00:00", "error": None}
        cache = weather.WeatherCache()
        cache.value, cache.location, cache.next_attempt = value, ("Changsha", 28.19874, 112.97087), 900
        with patch("weather.datetime", Clock), patch.dict(os.environ, {}, clear=True), patch("weather.time.monotonic", side_effect=[1, 2]), patch("weather.read_weather", side_effect=RuntimeError("fail")) as fetch:
            failed = cache.get()
            self.assertIsNone(failed["high_c"])
            self.assertIsNone(failed["low_c"])
            self.assertEqual(failed["humidity_percent"], 70)
            self.assertIsNotNone(failed["error"])
            self.assertEqual(cache.get(), failed)
            self.assertEqual(fetch.call_count, 1)

    def test_cache_retains_old_observation_and_marks_error(self):
        value = {"city": "Changsha", "condition": "Clear", "temperature_c": 20.0, "updated_at": "2026-10-28T00:00:00+00:00", "error": None}
        cache = weather.WeatherCache(success_ttl=900, retry_ttl=120)
        with patch.dict(os.environ, {}, clear=True), patch("weather.time.monotonic", side_effect=[0, 1, 901, 902]), patch("weather.read_weather", side_effect=[value, RuntimeError("fail")]) as fetch:
            self.assertEqual(cache.get(), value)
            self.assertEqual(cache.get(), value)
            failed = cache.get()
            self.assertEqual(failed["updated_at"], value["updated_at"])
            self.assertEqual(failed["temperature_c"], 20.0)
            self.assertIsNotNone(failed["error"])
            self.assertEqual(cache.get(), failed)
            self.assertEqual(fetch.call_count, 2)


if __name__ == "__main__":
    unittest.main()
