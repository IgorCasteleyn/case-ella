# Belgian Weather Explorer

**Author:** Casteleyn igor
**Date:** 3 September 2026  
**Context:** Technical Assessment for Ella Energy (Software / Data Engineer)  
**Repository:** <https://github.com/IgorCasteleyn/case-ella>

## Quickstart (Zero-Configuration)

The entire application starts via a single command from a clean clone:

```bash
docker compose up --build
```

### Endpoints

* **Dashboard (Next.js):** [http://localhost:3000](http://localhost:3000)
* **API Documentation (FastAPI / Swagger):** [http://localhost:8000/docs](http://localhost:8000/docs)
* **Database (PostgreSQL):** `localhost:5432` (`user: postgres`, `password: postgres`, `db: weather_db`)

### Clean Boot Lifecycle

On initial boot, the backend entrypoint (`wait_for_db.py`):

1. Waits for PostgreSQL to become healthy via `pg_isready`.

2. Executes schema migrations and seeds reference cities (Brussels, Ghent, Antwerp).

3. Checks for existing forecast data; if none exists, triggers a live Open-Meteo ingestion run.

4. Ensures revision history is testable on cold-start: if a city has fewer than two successful runs, `seed_demo_history()` inserts two explicit reviewer fixtures (T-24h and T-48h). These are not additional API fetches; they copy the live run's horizon with fixed temperature and wind offsets so the revision chart shows multiple points immediately.

5. Starts the API server once data is verified. The reviewer can view populated charts without executing manual seed scripts.

---

## 1. Data Modeling & The Forecast Revision Problem

### The Bitemporal Challenge

Weather forecasts for power markets and grid operation are updated continuously. Overwriting rows on new ingest runs causes irreversible data loss. To answer both *"what is the latest forecast for tomorrow at 14:00?"* and *"what did the forecast for that hour look like yesterday?"*, the data model separates physical time from operational time:

* **Valid Time (`target_time`):** The future hour being forecasted.

* **Reference Time (`run_at`):** The timestamp when our system fetched the forecast run.

### PostgreSQL Schema Architecture

* **`cities`:** Reference entity for tracked locations (`id`, `name`, `latitude`, `longitude`).

* **`forecast_runs`:** Operational ledger recording every ingestion batch per city (`id` UUID, `city_id` FK, `run_at` TIMESTAMPTZ, `status` success/failed, `error_message` TEXT).

* **`forecast_values`:** Time-series value records (`id` BIGSERIAL, `run_id` FK CASCADE, `city_id` FK CASCADE, `target_time` TIMESTAMPTZ, `temperature_2m` FLOAT, `wind_speed_10m` FLOAT).

### Constraints & Query Optimization

* **Uniqueness:** `UNIQUE (city_id, run_id, target_time)` guarantees that a single ingestion run cannot insert duplicate target timestamps for any city.

* **Run Uniqueness:** `UNIQUE (city_id, run_at)` on `forecast_runs` guarantees at the database level that no city can have duplicate runs for the same hourly reference window.

* **Query Index:** A composite B-tree index on `(city_id, target_time, run_id)` accelerates history lookups filtered by city and target hour.

* **Latest resolution:** `/api/v1/forecasts/latest` does not merge runs per target hour. It selects the single most recent successful `forecast_run` for the city and returns all of that run's values from the current UTC hour onward. Every point in the response shares the same `forecast_run_at`, keeping the displayed horizon internally consistent.

---

## 2. Operational Safety & Resilience

The ingestion engine (`backend/ingest.py`) is engineered to be safe to run continuously under adverse external conditions:

### 1. Atomicity (All-or-Nothing Writes)

* Ingestion executes within an explicit database transaction per city (`session.begin()`).

* If Open-Meteo drops a connection, sends malformed JSON, or the process crashes mid-batch, the transaction for that city rolls back immediately.

* The database is never left with a partial 12-hour batch instead of the expected 168-hour forecast.

### 2. Idempotency (Repeatable Runs)

* Timestamps are bucketed to the current UTC hour:

```python
current_run_hour = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)

```

* Before dispatching HTTP calls, the worker inspects `forecast_runs` for an existing `success` record matching `(city_id, current_run_hour)`.

* If found, the city is skipped with an informational log. Running the pipeline multiple times within the same hour produces zero duplicate rows and zero redundant external API calls.

### 3. Resilience & Failure Isolation

* External calls use `httpx.Client(timeout=5.0)` to eliminate hanging socket connections.

* Error boundaries isolate each city. If Open-Meteo returns a 500 error or times out for Ghent:

1. Ghent's open data transaction is rolled back.

2. A failed record is written to `forecast_runs` with the stacktrace summary.

3. The loop proceeds immediately to Antwerp and Brussels without aborting the pipeline.

### 4. Parser Validation (Automated Tests)

Before any parsed values enter a database transaction, `_parse_forecast_values` in `backend/ingest.py` validates Open-Meteo hourly arrays for structural integrity. Automated unit tests in `backend/tests/test_parser.py` exercise this gate in memory (no PostgreSQL connection, no network calls):

* **`test_parse_valid_payload`:** A well-formed payload with two time steps produces two `ForecastValue` records with correct float mappings.
* **`test_parse_mismatched_lengths_fails`:** Unequal array lengths (`time` vs. `temperature_2m` vs. `wind_speed_10m`) raise `ValueError`.
* **`test_parse_none_values_fails`:** `null` entries in the temperature or wind arrays raise `ValueError`.

These tests prove that corrupt upstream payloads are rejected before they reach the database, preventing partial or malformed batches from poisoning the forecast dataset.

To run them against a live stack:

```bash
docker compose exec backend pytest
```

---

## 3. API Surface (`FastAPI`)

The read-only API serves structured JSON backed by Pydantic v2 validation models:

| Method | Endpoint | Query Parameters | Description |
| --- | --- | --- | --- |
| `GET` | `/api/v1/cities` | None | Returns supported Belgian cities for frontend selection. |
| `GET` | `/api/v1/forecasts/latest` | `city_id: int` | Returns forecast points from the most recent successful run for the city (`target_time >=` current UTC hour). The frontend trims this to a 72-hour window; all points originate from one complete run for horizon consistency. |
| `GET` | `/api/v1/forecasts/history` | `city_id: int`, `target_time: datetime` | Returns the revision timeline for a specific hour across runs, ordered by `run_at ASC` to visualize forecast drift.

### Error Contracts

* Non-existent `city_id` parameters return `404 Not Found` with a descriptive message.

* Invalid datetime formats on history endpoints return `422 Unprocessable Entity` generated by Pydantic's type parsers.

---

## 4. Frontend Dashboard (`Next.js` + `shadcn/ui`)

The dashboard (`frontend/app/page.tsx`) provides an interactive interface built around two coordinated views:

* **City Selector:** Populated dynamically via `GET /api/v1/cities`.

* **Primary View (Latest Forecast):** Recharts visualization displaying expected temperature (°C) and wind speed (km/h) for the next 72 hours.

* **Secondary View (Revision Drift / Stretch Goal):** Clicking any point on the primary timeline queries `GET /api/v1/forecasts/history` for that exact `target_time`. The lower card renders the delta across runs, showing how numerical weather predictions converged as the target time approached.

---

## 5. Bonus: Scheduled Execution

### Implementation Choice: In-Compose Scheduled Worker

A dedicated worker service is configured in `docker-compose.yml` running an hourly ingestion cycle:

```yaml
cron:
    build:
      context: ./backend
      dockerfile: Dockerfile
    restart: unless-stopped
    entrypoint: []
    command: sh -c "while true; do sleep 3600; python ingest.py; done"
    depends_on:
      backend:
        condition: service_healthy
    environment:
      POSTGRES_HOST: db
      POSTGRES_PORT: "5432"
      POSTGRES_DB: weather_db
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      DATABASE_URL: postgresql://postgres:postgres@db:5432/weather_db

```

### Justification: Docker Compose vs. GitHub Actions

* **GitHub Actions:** Ideal for production serverless triggers, but creates an external cloud dependency that violates the prompt requirement: *"Everything runs via docker compose up from a fresh clone. No manual setup steps"*. Reviewers cannot evaluate scheduled pipelines offline or in local CI environments without setting up repository secrets.

* **In-Compose Worker:** Keeps the entire architecture hermetic, self-contained, and locally testable with zero configuration.

---

## 6. Prioritization & Scope Cuts

To deliver a production-grade data pipeline within the 4-hour constraint, scope was cut deliberately to focus on data engineering reliability rather than peripheral features:

* **Cut: Authentication & Authorization (JWT / RBAC):** This project represents an internal analytical service. Implementing OAuth or API keys would consume engineering time without demonstrating core data modeling or time-series competencies.

* **Cut: Full Atmospheric Parameter Suite:** Limited ingestion to temperature and wind speed. In power grid forecasting, temperature drives residential heat demand while wind speed dictates wind farm load factors; secondary parameters (humidity, UV, soil pressure) were omitted to preserve clarity.

* **Cut: Multi-Route Navigation & Theming:** Omitted routing libraries and theme toggles in favor of a robust single-page interface with a working revision history chart (the stretch goal).

See `specs/scope_and_tradeoffs.md` for the initial scoping matrix drafted before implementation.

---

## 7. AI-Assisted Engineering Workflow

Development utilized Cursor Pro under strict human direction. Rather than allowing unguided code synthesis, work followed a four-stage process:

```text
[1. Problem Decomposition] -> [2. Spec Authoring in /specs] -> [3. Context Prompting] -> [4. Code Verification & Review]
```

### 1. Specification-First Authoring

Before generating code, technical constraints were codified in Markdown files committed directly to git:

* `specs/architecture.md`: Data flow, ASCII topologies, and module contracts.

* `specs/scope_and_tradeoffs.md`: Trade-off matrix defining technical boundaries.

### 2. Manual Corrections to AI Output

Cursor Pro was prompted using localized file contexts (e.g. `@specs/architecture.md`, `@backend/models.py`), but required critical corrections on domain logic:

* **UUID Idempotency Leak:** Cursor initially generated random UUIDs for `ForecastRun` without checking previous runs, resulting in duplicate records on repeated execution. I intervened to add the hourly floor check (`current_run_hour`) before any DB insert.
* **Session Rollback Scoping:** Cursor initially wrapped the external HTTP request inside an open database transaction block. I separated the network call from the database transaction so slow API responses do not hold idle database connections open.

* **Reviewer fixtures for revision history:** Cursor did not anticipate that reviewers evaluating a fresh clone would only see one data point on the history chart. I added `seed_demo_history()` with explicit T-24h and T-48h fixtures: copies of the live run with fixed offsets, not separate Open-Meteo fetches. This makes the revision graph testable on cold-start without misrepresenting the data as real historical ingest runs.

---

## 8. With More Time: Architectural Evolution

If extending this system beyond the 4-hour prototype, the following improvements would be prioritized:

* **Alembic Migrations:** Replace declarative `Base.metadata.create_all()` with tracked Alembic revision scripts to handle production database migrations safely.
* **TimescaleDB Extension:** Convert `forecast_values` into a PostgreSQL Hypertable partitioned by `target_time` to maximize compression and query throughput over billions of forecast points.
* **Distributed Task Queue:** Migrate the in-container loop to Celery or Temporal backed by Redis, decoupling job dispatching from execution.
* **End-to-End Testing Pipeline:** Add automated container integration tests simulating network partitioning, API timeouts, and payload corruption using wiremock.

---

## 9. Live Extension Reasoning (Debrief Preparation)

### Scaling to 10,000 Locations

1. **API Batching:** Open-Meteo allows querying multiple coordinates in a single request. Querying locations in batches of 100 reduces HTTP network overhead by 99%.
2. **Worker Concurrency:** Replace the single-process ingestion loop with asynchronous worker pools (e.g., Celery or `asyncio.gather` with rate-limiting semaphores).
3. **Database Partitioning:** Implement PostgreSQL native range partitioning on `forecast_values` by `target_time` (e.g., monthly tables) to prevent B-tree indexes from exceeding RAM capacity.

### Integrating Multiple Forecast Providers (ECMWF, GFS, KMI)

1. **Provider Abstraction:** Define an abstract base class `BaseWeatherProvider` enforcing an identical signature:

```python
class BaseWeatherProvider(ABC):
    @abstractmethod
    async def fetch_forecast(self, lat: float, lon: float) -> list[StandardForecastRecord]:
        pass

```

1. **Schema Extension:** Add `provider_id` to `forecast_runs` and update its constraint to `UNIQUE (provider_id, city_id, run_at)`. The child table `forecast_values` remains unchanged, as its foreign key `run_id` already uniquely resolves to the specific provider's execution.
