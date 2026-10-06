import logging
import math

import functions_framework
import requests

from config import HTTP_TIMEOUT_SECONDS, required
from db import upsert_rows

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

URL = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/O-A0003-001"
# 可以查天氣高低溫！
# 測站代號 -> 對外縣市名。桃園沒有市區測站，用新屋站代表。
STATIONS = {
    "466920": "臺北",
    "466881": "新北",
    "467050": "桃園",
    "467490": "臺中",
    "467410": "臺南",
    "467441": "高雄",
}
STATION_NAME_OVERRIDES = {"新屋": "桃園"}

COLUMNS = (
    "cityName", "uvIndex", "airTemperature", "date", "weather", "humidity",
    "maxTemperature", "minTemperature",
)


def _fetch() -> list[dict]:
    params = {
        "Authorization": required("CWA_API_TOKEN"),
        "StationId": ",".join(STATIONS),
        "WeatherElement": "Weather,AirTemperature,UVIndex,RelativeHumidity,DailyHigh,DailyLow",
        "GeoInfo": "StationAltitude",
    }
    response = requests.get(URL, params=params, timeout=HTTP_TIMEOUT_SECONDS)
    response.raise_for_status()
    payload = response.json()

    # CWA 的 success 有時是字串 "true"，有時是布林值
    if str(payload.get("success")).lower() != "true":
        raise ValueError("CWA API 回應 success 不為 true")
    return payload["records"]["Station"]


def _daily_temperature(elements: dict, extreme: str) -> float | None:
    """當日截至觀測時間的極值（攝氏）；缺測或儀器故障回傳 None。"""
    value = (
        elements.get("DailyExtreme", {}).get(extreme, {})
        .get("TemperatureInfo", {}).get("AirTemperature")
    )
    try:
        temperature = float(value)
    except (TypeError, ValueError):
        return None
    return temperature if math.isfinite(temperature) and temperature != -99 else None


def _to_row(station: dict) -> tuple:
    name = station["StationName"]
    elements = station["WeatherElement"]
    return (
        STATION_NAME_OVERRIDES.get(name, name),
        elements["UVIndex"],
        elements["AirTemperature"],
        station["ObsTime"]["DateTime"],
        elements["Weather"],
        elements["RelativeHumidity"],
        _daily_temperature(elements, "DailyHigh"),
        _daily_temperature(elements, "DailyLow"),
    )


@functions_framework.http
def cwa_uv_live(request):
    try:
        stations = _fetch()
    except (requests.RequestException, ValueError, KeyError):
        logger.exception("讀取 CWA API 失敗")
        return "Failed to get data from API", 502

    try:
        count = upsert_rows("cwa_uv_live", COLUMNS, "cityName", [
            _to_row(station) for station in stations
        ])
    except Exception:
        logger.exception("寫入 cwa_uv_live 失敗")
        return "Failed to write data", 500

    return f"OK, {count} rows", 200
