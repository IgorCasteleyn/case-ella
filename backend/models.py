"""Declaratieve SQLAlchemy-modellen voor het bitemporele forecast-datamodel."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class City(Base):
    __tablename__ = "cities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)

    forecast_runs: Mapped[list[ForecastRun]] = relationship(back_populates="city")
    forecast_values: Mapped[list[ForecastValue]] = relationship(back_populates="city")


class ForecastRun(Base):
    __tablename__ = "forecast_runs"
    __table_args__ = (UniqueConstraint("city_id", "run_at", name="uq_city_run_at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id"), nullable=False)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    city: Mapped[City] = relationship(back_populates="forecast_runs")
    forecast_values: Mapped[list[ForecastValue]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )


class ForecastValue(Base):
    __tablename__ = "forecast_values"
    __table_args__ = (
        UniqueConstraint("city_id", "run_id", "target_time", name="uq_city_run_target"),
        Index(
            "ix_forecast_values_city_id_target_time_run_id",
            "city_id",
            "target_time",
            "run_id",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("forecast_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id"), nullable=False)
    target_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    temperature_2m: Mapped[float] = mapped_column(Float, nullable=False)
    wind_speed_10m: Mapped[float] = mapped_column(Float, nullable=False)

    run: Mapped[ForecastRun] = relationship(back_populates="forecast_values")
    city: Mapped[City] = relationship(back_populates="forecast_values")
