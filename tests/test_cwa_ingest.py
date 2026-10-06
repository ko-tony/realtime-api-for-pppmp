import importlib.util
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock, patch

CLOUDRUN = Path(__file__).resolve().parents[1] / "cloudrun"
sys.path.insert(0, str(CLOUDRUN))
try:
    spec = importlib.util.spec_from_file_location("cwa_ingest", CLOUDRUN / "get-cwa-uv-live.py")
    ingest = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ingest)
finally:
    sys.path.pop(0)

STATION = {
    "StationName": "新屋",
    "ObsTime": {"DateTime": "2026-10-06T12:00:00+08:00"},
    "WeatherElement": {
        "UVIndex": 6, "AirTemperature": 28.5,
        "Weather": "晴", "RelativeHumidity": 70,
        "DailyExtreme": {
            "DailyHigh": {"TemperatureInfo": {"AirTemperature": 32.1}},
            "DailyLow": {"TemperatureInfo": {"AirTemperature": "24.3"}},
        },
    },
}


class CwaIngestTest(unittest.TestCase):
    def test_fetch_and_write_daily_extremes(self):
        with patch.object(ingest, "required", return_value="test-token"), \
             patch.object(ingest.requests, "get") as get, \
             patch.object(ingest, "upsert_rows", return_value=1) as write:
            get.return_value.json.return_value = {
                "success": "true", "records": {"Station": [STATION]},
            }
            self.assertEqual(ingest.cwa_uv_live(Mock()), ("OK, 1 rows", 200))
            requested = get.call_args.kwargs["params"]["WeatherElement"].split(",")
            self.assertIn("DailyHigh", requested)
            self.assertIn("DailyLow", requested)
            table, columns, key, rows = write.call_args.args
            self.assertEqual((table, key), ("cwa_uv_live", "cityName"))
            row = dict(zip(columns, rows[0], strict=True))
            self.assertEqual(row["cityName"], "桃園")
            self.assertEqual(row["airTemperature"], 28.5)
            self.assertEqual(row["maxTemperature"], 32.1)
            self.assertEqual(row["minTemperature"], 24.3)

    def test_missing_and_invalid_extreme_is_null_without_losing_other_temperature(self):
        for value in (None, -99, "-99.0", "X", "", "NaN", "Infinity"):
            with self.subTest(value=value):
                station = deepcopy(STATION)
                station["WeatherElement"]["DailyExtreme"]["DailyHigh"]["TemperatureInfo"]["AirTemperature"] = value
                row = dict(zip(ingest.COLUMNS, ingest._to_row(station), strict=True))
                self.assertIsNone(row["maxTemperature"])
                self.assertEqual(row["minTemperature"], 24.3)
        station = deepcopy(STATION)
        del station["WeatherElement"]["DailyExtreme"]
        row = dict(zip(ingest.COLUMNS, ingest._to_row(station), strict=True))
        self.assertIsNone(row["maxTemperature"])
        self.assertIsNone(row["minTemperature"])

    def test_valid_subzero_temperature(self):
        self.assertEqual(ingest._daily_temperature({
            "DailyExtreme": {"DailyLow": {"TemperatureInfo": {"AirTemperature": -3.2}}},
        }, "DailyLow"), -3.2)
