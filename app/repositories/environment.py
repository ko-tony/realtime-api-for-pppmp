from sqlalchemy import Row, func, select
from sqlalchemy.orm import Session

from app import models

# moenv_live 的縣市名帶「市」（臺北市），cwa_uv_live 不帶（臺北）。
# 兩個政府來源命名不一致，資料表正規化前只能在 JOIN 時對齊。
_MOENV_CITY_KEY = func.replace(models.MoenvLive.cityName, "市", "")


def list_environment(db: Session) -> list[Row]:
    statement = (
        select(
            models.MoenvLive.cityName.label("cityName"),
            models.MoenvLive.aqi.label("aqi"),
            models.MoenvLive.pm25.label("pm25"),
            models.MoenvLive.o3.label("o3"),
            models.MoenvLive.date.label("aqiDate"),
            models.CwaUvLive.airTemperature.label("airTemperature"),
            models.CwaUvLive.maxTemperature.label("maxTemperature"),
            models.CwaUvLive.minTemperature.label("minTemperature"),
            models.CwaUvLive.humidity.label("humidity"),
            models.CwaUvLive.uvIndex.label("uvIndex"),
            models.CwaUvLive.weather.label("weather"),
            models.CwaUvLive.date.label("weatherDate"),
        )
        .join(models.CwaUvLive, _MOENV_CITY_KEY == models.CwaUvLive.cityName)
        .order_by(models.MoenvLive.cityName)
    )
    return list(db.execute(statement).all())
