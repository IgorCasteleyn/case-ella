"""Read-only FastAPI voor steden, actuele forecasts en forecast-historie."""

from __future__ import annotations

import logging
from collections.abc import Generator
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session

try:
    from backend.database import SessionLocal
    from backend.models import City, ForecastRun, ForecastValue
    from backend.schemas import (
        CityResponse,
        ForecastHistoryResponse,
        ForecastPoint,
        HistoryPoint,
        LatestForecastResponse,
    )
except ImportError:
    from database import SessionLocal
    from models import City, ForecastRun, ForecastValue
    from schemas import (
        CityResponse,
        ForecastHistoryResponse,
        ForecastPoint,
        HistoryPoint,
        LatestForecastResponse,
    )

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("api")

app = FastAPI(title="Ella Weather API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    except Exception:
        session.rollback()
        logger.exception("Database-sessie teruggedraaid na fout")
        raise
    finally:
        session.close()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _current_utc_hour() -> datetime:
    return datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)


def _get_city_or_404(session: Session, city_id: int) -> City:
    city = session.get(City, city_id)
    if city is None:
        raise HTTPException(status_code=404, detail="Stad niet gevonden")
    return city


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/cities", response_model=list[CityResponse])
def list_cities(db: Session = Depends(get_db)) -> list[City]:
    return list(db.scalars(select(City).order_by(City.id)).all())


@app.get("/api/v1/forecasts/latest", response_model=LatestForecastResponse)
def get_latest_forecast(
    city_id: int = Query(...),
    db: Session = Depends(get_db),
) -> LatestForecastResponse:
    city = _get_city_or_404(db, city_id)

    latest_run = db.scalar(
        select(ForecastRun)
        .where(
            ForecastRun.city_id == city.id,
            ForecastRun.status == "success",
        )
        .order_by(ForecastRun.run_at.desc())
        .limit(1)
    )
    if latest_run is None:
        return LatestForecastResponse(
            city_id=city.id,
            city_name=city.name,
            forecasts=[],
        )

    values = db.scalars(
        select(ForecastValue)
        .where(
            ForecastValue.run_id == latest_run.id,
            ForecastValue.target_time >= _current_utc_hour(),
        )
        .order_by(ForecastValue.target_time.asc())
    ).all()

    return LatestForecastResponse(
        city_id=city.id,
        city_name=city.name,
        forecasts=[
            ForecastPoint(
                target_time=value.target_time,
                temperature_2m=value.temperature_2m,
                wind_speed_10m=value.wind_speed_10m,
                forecast_run_at=latest_run.run_at,
            )
            for value in values
        ],
    )


@app.get("/api/v1/forecasts/history", response_model=ForecastHistoryResponse)
def get_forecast_history(
    city_id: int = Query(...),
    target_time: datetime = Query(...),
    db: Session = Depends(get_db),
) -> ForecastHistoryResponse:
    city = _get_city_or_404(db, city_id)
    normalized_target = _as_utc(target_time)

    rows = db.execute(
        select(ForecastValue, ForecastRun)
        .join(ForecastRun, ForecastValue.run_id == ForecastRun.id)
        .where(
            ForecastValue.city_id == city.id,
            ForecastValue.target_time == normalized_target,
            ForecastRun.status == "success",
        )
        .order_by(ForecastRun.run_at.asc())
    ).all()

    return ForecastHistoryResponse(
        city_id=city.id,
        target_time=normalized_target,
        history=[
            HistoryPoint(
                forecast_run_at=run.run_at,
                temperature_2m=value.temperature_2m,
                wind_speed_10m=value.wind_speed_10m,
            )
            for value, run in rows
        ],
    )
