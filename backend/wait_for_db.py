"""Wacht tot PostgreSQL verbindingen accepteert voordat de backend start."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time

import psycopg2

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("wait_for_db")

MAX_ATTEMPTS = 30
DELAY_SECONDS = 1.0
CONNECT_TIMEOUT_SECONDS = 3


def wait_for_db() -> None:
    host = os.environ.get("POSTGRES_HOST", "db")
    port = int(os.environ.get("POSTGRES_PORT", "5432"))
    user = os.environ.get("POSTGRES_USER", "postgres")
    password = os.environ.get("POSTGRES_PASSWORD", "postgres")
    dbname = os.environ.get("POSTGRES_DB", "weather_db")

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            connection = psycopg2.connect(
                host=host,
                port=port,
                user=user,
                password=password,
                dbname=dbname,
                connect_timeout=CONNECT_TIMEOUT_SECONDS,
            )
            connection.close()
            logger.info("Database is bereikbaar (poging %s/%s)", attempt, MAX_ATTEMPTS)
            return
        except psycopg2.OperationalError as exc:
            logger.warning(
                "Database nog niet klaar (poging %s/%s): %s",
                attempt,
                MAX_ATTEMPTS,
                exc,
            )
            time.sleep(DELAY_SECONDS)

    raise RuntimeError(f"Database niet bereikbaar na {MAX_ATTEMPTS} pogingen")


def run_seed() -> None:
    seed_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seed.py")
    logger.info("Database seed starten")
    result = subprocess.run([sys.executable, seed_path], check=False)
    if result.returncode != 0:
        raise RuntimeError(f"seed.py mislukt met exitcode {result.returncode}")
    logger.info("Database seed voltooid")


def _has_successful_forecast_run() -> bool:
    connection = psycopg2.connect(
        host=os.environ.get("POSTGRES_HOST", "db"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        user=os.environ.get("POSTGRES_USER", "postgres"),
        password=os.environ.get("POSTGRES_PASSWORD", "postgres"),
        dbname=os.environ.get("POSTGRES_DB", "weather_db"),
        connect_timeout=CONNECT_TIMEOUT_SECONDS,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM forecast_runs WHERE status = %s LIMIT 1",
                ("success",),
            )
            return cursor.fetchone() is not None
    finally:
        connection.close()


def run_initial_ingest_if_empty() -> None:
    try:
        if _has_successful_forecast_run():
            logger.info(
                "Succesvolle forecast-run aanwezig; initiële ingest overgeslagen"
            )
            return
    except psycopg2.Error:
        logger.exception("Kon forecast_runs niet controleren")
        raise

    ingest_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ingest.py")
    logger.info("Geen succesvolle forecast-run gevonden; ingest.py starten")
    result = subprocess.run([sys.executable, ingest_path], check=False)
    if result.returncode != 0:
        raise RuntimeError(f"ingest.py mislukt met exitcode {result.returncode}")
    logger.info("Initiële ingest voltooid")


def main() -> None:
    wait_for_db()
    run_seed()
    run_initial_ingest_if_empty()
    if len(sys.argv) < 2:
        raise RuntimeError("Geen commando opgegeven na database-wacht")
    os.execvp(sys.argv[1], sys.argv[1:])


if __name__ == "__main__":
    main()
