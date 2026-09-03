"""Unit tests voor Open-Meteo payload parsing (_parse_forecast_values)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from ingest import _parse_forecast_values


def test_parse_valid_payload() -> None:
    run_id = uuid.uuid4()
    city_id = 1
    payload = {
        "hourly": {
            "time": ["2026-09-03T10:00", "2026-09-03T11:00"],
            "temperature_2m": [18.5, 19.2],
            "wind_speed_10m": [12.3, 14.7],
        }
    }

    values = _parse_forecast_values(payload, city_id, run_id)

    assert len(values) == 2

    assert values[0].run_id == run_id
    assert values[0].city_id == city_id
    assert values[0].target_time == datetime(2026, 9, 3, 10, 0, tzinfo=timezone.utc)
    assert values[0].temperature_2m == 18.5
    assert values[0].wind_speed_10m == 12.3

    assert values[1].run_id == run_id
    assert values[1].city_id == city_id
    assert values[1].target_time == datetime(2026, 9, 3, 11, 0, tzinfo=timezone.utc)
    assert values[1].temperature_2m == 19.2
    assert values[1].wind_speed_10m == 14.7


def test_parse_mismatched_lengths_fails() -> None:
    payload = {
        "hourly": {
            "time": ["2026-09-03T10:00", "2026-09-03T11:00"],
            "temperature_2m": [18.5],
            "wind_speed_10m": [12.3, 14.7],
        }
    }

    with pytest.raises(ValueError, match="ongelijke lengte"):
        _parse_forecast_values(payload, city_id=1, run_id=uuid.uuid4())


@pytest.mark.parametrize(
    "temperatures,wind_speeds",
    [
        ([None], [12.3]),
        ([18.5], [None]),
    ],
)
def test_parse_none_values_fails(
    temperatures: list[float | None],
    wind_speeds: list[float | None],
) -> None:
    payload = {
        "hourly": {
            "time": ["2026-09-03T10:00"],
            "temperature_2m": temperatures,
            "wind_speed_10m": wind_speeds,
        }
    }

    with pytest.raises(ValueError, match="Ontbrekende meetwaarde"):
        _parse_forecast_values(payload, city_id=1, run_id=uuid.uuid4())
