"""Pydantic-responsmodellen voor de read-only FastAPI-laag."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    latitude: float
    longitude: float


class ForecastPoint(BaseModel):
    target_time: datetime
    temperature_2m: float
    wind_speed_10m: float
    forecast_run_at: datetime


class LatestForecastResponse(BaseModel):
    city_id: int
    city_name: str
    forecasts: list[ForecastPoint]


class HistoryPoint(BaseModel):
    forecast_run_at: datetime
    temperature_2m: float
    wind_speed_10m: float


class ForecastHistoryResponse(BaseModel):
    city_id: int
    target_time: datetime
    history: list[HistoryPoint]
