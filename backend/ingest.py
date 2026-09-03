"""Haalt Open-Meteo forecasts op en schrijft ze bitemporeel weg per stad."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select

try:
    from backend.database import SessionLocal
    from backend.models import City, ForecastRun, ForecastValue
except ImportError:
    from database import SessionLocal
    from models import City, ForecastRun, ForecastValue

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("ingest")

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


@dataclass(frozen=True)
class CityRef:
    id: int
    name: str
    latitude: float
    longitude: float


_CITY_FAILURES = (
    httpx.TimeoutException,
    httpx.RequestError,
    httpx.HTTPStatusError,
    json.JSONDecodeError,
    KeyError,
    ValueError,
    TypeError,
)


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_forecast_values(
    payload: dict[str, Any],
    city_id: int,
    run_id: uuid.UUID,
) -> list[ForecastValue]:
    hourly = payload["hourly"]
    times = hourly["time"]
    temperatures = hourly["temperature_2m"]
    wind_speeds = hourly["wind_speed_10m"]

    if not (
        isinstance(times, list)
        and isinstance(temperatures, list)
        and isinstance(wind_speeds, list)
    ):
        raise ValueError("Open-Meteo hourly velden zijn geen arrays")

    if not times:
        raise ValueError("Open-Meteo hourly arrays zijn leeg")

    if not (len(times) == len(temperatures) == len(wind_speeds)):
        raise ValueError("Open-Meteo hourly arrays hebben ongelijke lengte")

    values: list[ForecastValue] = []
    for time_str, temperature, wind_speed in zip(
        times, temperatures, wind_speeds, strict=True
    ):
        if temperature is None or wind_speed is None:
            raise ValueError(f"Ontbrekende meetwaarde voor {time_str}")
        values.append(
            ForecastValue(
                run_id=run_id,
                city_id=city_id,
                target_time=_parse_utc(time_str),
                temperature_2m=float(temperature),
                wind_speed_10m=float(wind_speed),
            )
        )
    return values


def _record_failed_run(
    city_id: int,
    current_run_hour: datetime,
    error_message: str,
) -> None:
    try:
        with SessionLocal() as session:
            with session.begin():
                session.add(
                    ForecastRun(
                        id=uuid.uuid4(),
                        city_id=city_id,
                        run_at=current_run_hour,
                        status="failed",
                        error_message=error_message,
                    )
                )
    except Exception:
        logger.exception(
            "Kon failed ForecastRun niet wegschrijven voor city_id=%s",
            city_id,
        )


def _ingest_city(
    client: httpx.Client,
    city: CityRef,
    current_run_hour: datetime,
) -> None:
    try:
        with SessionLocal() as session:
            with session.begin():
                existing = session.scalar(
                    select(ForecastRun.id).where(
                        ForecastRun.city_id == city.id,
                        ForecastRun.run_at == current_run_hour,
                        ForecastRun.status == "success",
                    )
                )
                if existing is not None:
                    logger.info(
                        "Stad %s is al succesvol ingeslagen voor run_at=%s; overgeslagen",
                        city.name,
                        current_run_hour.isoformat(),
                    )
                    return

                response = client.get(
                    FORECAST_URL,
                    params={
                        "latitude": city.latitude,
                        "longitude": city.longitude,
                        "hourly": "temperature_2m,wind_speed_10m",
                        "timezone": "UTC",
                    },
                )
                response.raise_for_status()
                payload = response.json()

                run_id = uuid.uuid4()
                session.add(
                    ForecastRun(
                        id=run_id,
                        city_id=city.id,
                        run_at=current_run_hour,
                        status="success",
                    )
                )
                session.add_all(_parse_forecast_values(payload, city.id, run_id))
                logger.info(
                    "Stad %s succesvol ingeslagen (%s uurwaarden)",
                    city.name,
                    len(payload["hourly"]["time"]),
                )
    except _CITY_FAILURES as exc:
        logger.exception("Ingestie mislukt voor stad %s: %s", city.name, exc)
        _record_failed_run(city.id, current_run_hour, str(exc))
    except Exception as exc:
        logger.exception("Onverwachte fout voor stad %s: %s", city.name, exc)
        _record_failed_run(city.id, current_run_hour, str(exc))


def ingest() -> None:
    current_run_hour = datetime.now(timezone.utc).replace(
        minute=0, second=0, microsecond=0
    )
    logger.info("Ingestie gestart voor run_at=%s", current_run_hour.isoformat())

    with SessionLocal() as session:
        cities = [
            CityRef(
                id=city.id,
                name=city.name,
                latitude=city.latitude,
                longitude=city.longitude,
            )
            for city in session.scalars(select(City).order_by(City.id)).all()
        ]

    if not cities:
        logger.warning("Geen steden in de database; ingestie afgebroken")
        return

    with httpx.Client(timeout=5.0) as client:
        for city in cities:
            _ingest_city(client, city, current_run_hour)

    logger.info("Ingestie afgerond")


if __name__ == "__main__":
    ingest()
