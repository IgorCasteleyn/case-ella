# Architecture Specification: Belgian Weather Explorer

## 1. Systeembeschrijving en Dataflow

Het systeem scheidt data-ingestie strikt van data-ontsluiting. Externe API-afhankelijkheden raken nooit de frontend of de backend read-laag[cite: 1].

```mermaid
[Open-Meteo API]
       |
       | HTTP GET (5s timeout)
       v
[Ingestion Worker]
       |
       | Transactie per stad (BEGIN / COMMIT / ROLLBACK)
       | Idempotent insert (ON CONFLICT DO NOTHING)
       v
[PostgreSQL Database]
       |
       | SQL Queries (DISTINCT ON voor actueel, filter voor historie)
       v
[FastAPI Backend]
       |
       | REST JSON API
       v
[Next.js Frontend]
```

---

## 2. Datamodel en Entiteiten

Om revisies van weersvoorspellingen betrouwbaar vast te leggen zonder dataverlies, hanteert het model twee tijdassen:

* Reference Time (`run_at` of `fetched_at`): Wanneer de voorspelling is binnengehaald.

* Valid Time (`target_time`): Het toekomstige uur waarover de voorspelling een uitspraak doet.

### Entiteiten

1. **cities**

* Doel: Referentietabel voor geselecteerde locaties (Brussel, Gent, Antwerpen).

* Velden: `id` (PK), `name` (VARCHAR), `latitude` (FLOAT), `longitude` (FLOAT).

1. **forecast_runs**

* Doel: Registratie van elke ingestie-poging per stad. Zorgt voor operationele traceerbaarheid.

* Velden: `id` (UUID, PK), `city_id` (FK -> cities.id), `run_at` (TIMESTAMPTZ), `status` (VARCHAR: 'success' | 'failed'), `error_message` (TEXT, nullable).

1. **forecast_values**

* Doel: De binnengehaalde numerieke waarden per run en per doel-uur.

* Velden: `id` (BIGSERIAL, PK), `run_id` (FK -> forecast_runs.id ON DELETE CASCADE), `city_id` (FK -> cities.id), `target_time` (TIMESTAMPTZ), `temperature_2m` (FLOAT), `wind_speed_10m` (FLOAT).
* Constraints: `UNIQUE (city_id, run_id, target_time)` om dubbele data binnen eenzelfde run uit te sluiten.

* Indexering: Composite index op `(city_id, target_time, run_id)` voor snelle subqueries naar de laatste run.

---

## 3. Ingestion Worker: Operationele Eisen

De worker haalt periodiek forecast-data op bij Open-Meteo en schrijft deze weg naar PostgreSQL.

* **Atomiciteit:**
* Ingestie wordt per stad uitgevoerd binnen een expliciete database-transactie (`BEGIN ... COMMIT`).

* Mislukt de API-aanroep, faalt parsing of crasht het netwerk halverwege, dan volgt een automatische `ROLLBACK`. Er blijft nooit een partiële dataset van een run achter.

* **Idempotentie:**
* De worker rondt de tijdstempel af op het lopende uur.
* Een herhaalde uitvoering binnen hetzelfde uur met dezelfde bron levert via `ON CONFLICT DO NOTHING` geen duplicate records of inconsistente data op.

* **Veerkracht (Resilience):**
* Externe HTTP-calls hebben een harde timeout van maximaal 5 seconden.

* Fouten per stad worden afgevangen (`try/except`). Als Open-Meteo faalt voor Gent, wordt de transactie voor Gent teruggedraaid, de fout gelogd in `forecast_runs` met status 'failed', en gaat het script door met Brussel en Antwerpen.

---

## 4. FastAPI Backend (Read-only API)

De backend communiceert uitsluitend met PostgreSQL en kent geen externe netwerkafhankelijkheden.

### Endpoints

1. `GET /api/v1/cities`

* Geeft de lijst van geconfigureerde steden terug voor de frontend dropdown.

1. `GET /api/v1/forecasts/latest?city_id={id}`

* Geeft de meest recente voorspelling voor de komende uren/dagen.

* Query-logica: Haalt records op gekoppeld aan de meest recente succesvolle `run_id` per `target_time`.

1. `GET /api/v1/forecasts/history?city_id={id}&target_time={iso_timestamp}`

* Geeft de chronologische revisiegeschiedenis terug voor een specifiek doel-uur.

* Query-logica: Filtert op `city_id` en `target_time`, gesorteerd op `forecast_runs.run_at ASC`. Hiermee wordt zichtbaar hoe de voorspelling over opeenvolgende runs evolueerde.

---

## 5. Next.js Frontend

Een minimalistisch dashboard gebouwd met Next.js en shadcn/ui.

* **City Selector:** Dropdown gevoed door `GET /api/v1/cities`.

* **Primary View (Latest Forecast):** Tijdreeksgrafiek met temperatuur en windsnelheid voor de geselecteerde stad.

* **Secondary View (Forecast Evolution):** Klikken op een datapunt (specifiek doel-uur) activeert een detailweergave die de data van `GET /api/v1/forecasts/history` toont in een delta/evolutiegrafiek.

---

## 6. Deployment en Orchestratie

Het volledige systeem start via `docker compose up` zonder handmatige configuratiestappen:

1. `db`: PostgreSQL container met persistente volume en healthcheck (`pg_isready`).

2. `backend`: Draait database-migraties, start de API-server, en triggert direct een initiële ingestie-run indien de database leeg is.

3. `frontend`: Draait de Next.js webapplicatie gekoppeld aan de backend container.
