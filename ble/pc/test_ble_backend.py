import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ble_backend import server, weather


class SeparateCollectorTests(unittest.TestCase):
    def test_snapshot_uses_codex_and_weather_without_wifi_bridge(self):
        five = {"remaining_percent": 71, "resets_at": None}
        week = {"remaining_percent": 42, "resets_at": None}
        meteo = {"city": "Changsha", "temperature_c": 23, "error": None}
        with patch.object(server, "read_codex", return_value=(five, week)), \
             patch.object(server.WeatherCache, "get", return_value=meteo):
            value = server.live_status()
        self.assertEqual(value["codex"]["five_hour"]["remaining_percent"], 71)
        self.assertEqual(value["weather"]["temperature_c"], 23)
        self.assertNotIn("deepseek", value)
        self.assertFalse(hasattr(server, "Handler"))

    def test_codex_failure_does_not_hide_weather(self):
        meteo = {"city": "Changsha", "temperature_c": 23, "error": None}
        with patch.object(server, "read_codex", side_effect=RuntimeError("unavailable")), \
             patch.object(server.WeatherCache, "get", return_value=meteo):
            value = server.live_status()
        self.assertIsNone(value["codex"]["five_hour"]["remaining_percent"])
        self.assertEqual(value["weather"]["temperature_c"], 23)


if __name__ == "__main__":
    unittest.main()
