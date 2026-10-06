from datetime import datetime

from pydantic import BaseModel, ConfigDict
from typing import Literal


class EnvironmentResponse(BaseModel):
    """單一縣市的空氣品質與天氣即時值。"""

    model_config = ConfigDict(from_attributes=True)

    cityName: str
    aqi: int | None
    pm25: int | float | None
    o3: int | float | None
    aqiDate: datetime | None
    airTemperature: float | None
    maxTemperature: float | None
    minTemperature: float | None
    humidity: int | None
    uvIndex: int | None
    weather: str | None
    weatherDate: datetime | None


class FinanceResponse(BaseModel):
    """大盤開盤每三分鐘抓一次，收盤後不抓。(機關有些許延遲)"""

    model_config = ConfigDict(from_attributes=True)

    symbol: str
    name: str
    index: float
    change: float | None
    turnover: float
    turnoverUnit: Literal["億元"] = "億元"
    date: datetime
    fetchedAt: datetime
