"""Maakt tabellen aan en zaait de drie referentie-steden indien ze ontbreken."""

from __future__ import annotations

import logging

from sqlalchemy import select

from database import SessionLocal, engine
from models import Base, City

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("seed")

CITIES = (
    {"name": "Brussel", "latitude": 50.8503, "longitude": 4.3517},
    {"name": "Gent", "latitude": 51.0543, "longitude": 3.7174},
    {"name": "Antwerpen", "latitude": 51.2194, "longitude": 4.4025},
)


def seed() -> None:
    Base.metadata.create_all(bind=engine)
    logger.info("Tabellen aangemaakt of al aanwezig")

    session = SessionLocal()
    try:
        for city_data in CITIES:
            existing = session.scalar(
                select(City).where(City.name == city_data["name"])
            )
            if existing is None:
                session.add(City(**city_data))
                logger.info("Stad toegevoegd: %s", city_data["name"])
            else:
                logger.info("Stad bestaat al: %s", city_data["name"])
        session.commit()
    except Exception:
        session.rollback()
        logger.exception("Seed transactie teruggedraaid")
        raise
    finally:
        session.close()


if __name__ == "__main__":
    seed()
