from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CwaUvLive(Base):
    __tablename__ = "cwa_uv_live"

    cityName: Mapped[str] = mapped_column(String, primary_key=True)
    airTemperature: Mapped[float | None] = mapped_column(Float)
    maxTemperature: Mapped[float | None] = mapped_column(Float)
    minTemperature: Mapped[float | None] = mapped_column(Float)
    uvIndex: Mapped[int | None] = mapped_column(Integer)
    date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    weather: Mapped[str | None] = mapped_column(String)
    humidity: Mapped[int | None] = mapped_column(Integer)


class MoenvLive(Base):
    __tablename__ = "moenv_live"

    cityName: Mapped[str] = mapped_column(String, primary_key=True)
    aqi: Mapped[int | None] = mapped_column(Integer)
    pm25: Mapped[float | None] = mapped_column(Numeric)
    o3: Mapped[float | None] = mapped_column(Numeric)
    date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FinanceLive(Base):
    __tablename__ = "finance_live"

    symbol: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    index: Mapped[float] = mapped_column(Numeric(12, 2))
    change: Mapped[float | None] = mapped_column(Numeric(12, 2))
    turnover: Mapped[float] = mapped_column(Numeric(20, 8))
    date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fetchedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True))
