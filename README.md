# Hospital Bulk Processing API

A FastAPI service for bulk-creating hospitals via CSV upload, integrating with the Hospital Directory API.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                  Hospital Bulk Processing API                │
│                                                             │
│  POST /hospitals/bulk  ──►  CSVParser  ──►  BulkService    │
│                                               │             │
│  GET  /hospitals/bulk/{id}/progress  ◄──  SQLite DB        │
│                                               │             │
│                                     HospitalAPIClient       │
│                                               │             │
└───────────────────────────────────────────────┼─────────────┘
                                                ▼
                              Hospital Directory API (external)
                              POST /hospitals/
                              PATCH /hospitals/batch/{id}/activate
```

**Key design decisions:**

- **Dependency Injection** — every collaborator (DB session, HTTP client, settings) is injected via FastAPI's `Depends`. Nothing is imported globally from service code.
- **Async throughout** — `asyncio.Semaphore` caps concurrent external API calls to avoid overwhelming the upstream service.
- **SQLAlchemy async + SQLite** — lightweight persistence; swap the `DATABASE_URL` for PostgreSQL in production.
- **Clean exceptions** — domain errors (`CSVValidationError`, `BatchNotFoundError`, …) are mapped to HTTP status codes in one place (the app factory), not scattered across routes.

## Project structure

```
app/
├── api/
│   ├── deps.py           # DI wiring (DB, HTTP client, services)
│   └── routes/
│       └── hospitals.py  # All route handlers
├── core/
│   ├── config.py         # pydantic-settings config
│   └── exceptions.py     # Domain exceptions
├── db/
│   └── session.py        # Async SQLAlchemy engine + get_db
├── models/
│   └── batch.py          # ORM models (Batch, HospitalRow)
├── schemas/
│   └── batch.py          # Pydantic request/response schemas
├── services/
│   ├── bulk_processing.py     # Orchestration logic
│   └── hospital_api_client.py # HTTP wrapper for external API
├── utils/
│   └── csv_parser.py     # CSV parsing + validation
└── main.py               # App factory + lifespan
tests/
├── conftest.py           # Shared fixtures (in-memory DB, mock API client)
├── unit/
│   ├── test_csv_parser.py
│   ├── test_bulk_service.py
│   └── test_hospital_api_client.py
└── integration/
    └── test_routes.py    # Full HTTP integration tests
```

## Quickstart

```bash
# 1. Clone and install
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Configure
cp .env.example .env

# 3. Run
uvicorn app.main:app --reload

# 4. Open docs
open http://localhost:8000/docs
```

## Docker

```bash
docker compose up --build
```

## Run tests

```bash
pytest -v
```

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/hospitals/bulk` | Upload CSV → create + activate hospitals |
| `POST` | `/api/v1/hospitals/bulk/validate` | Validate CSV without processing |
| `GET` | `/api/v1/hospitals/bulk` | List all batches |
| `GET` | `/api/v1/hospitals/bulk/{id}` | Get batch details |
| `GET` | `/api/v1/hospitals/bulk/{id}/progress` | Poll batch progress |
| `DELETE` | `/api/v1/hospitals/bulk/{id}` | Delete batch + hospitals |
| `GET` | `/health` | Health check |

## CSV format

```csv
name,address,phone
General Hospital,123 Main Street,555-0001
City Medical Center,456 Oak Avenue,
```

- `name` — required, max 255 chars
- `address` — required, max 500 chars
- `phone` — optional, max 50 chars
- Maximum **20 rows** per upload
- UTF-8 encoding required

## Processing workflow

```
Upload CSV
    │
    ▼
Validate (columns, row count, field lengths)
    │
    ▼
Generate batch UUID
    │
    ▼
Create hospitals concurrently (max 5 parallel)
    │     ├─ success → hospital_id stored
    │     └─ failure → error_message stored
    ▼
If any succeeded → PATCH /hospitals/batch/{id}/activate
    │
    ▼
Persist final status + return results
```

## Batch statuses

| Status | Meaning |
|--------|---------|
| `pending` | Created but not yet processing |
| `processing` | Currently creating hospitals |
| `completed` | All hospitals created and activated |
| `partially_failed` | Some succeeded, some failed |
| `failed` | All hospitals failed |
