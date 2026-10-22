# Backend — Platform pod

Python 3.12+ (3.14 locally via uv), FastAPI, Alembic, Postgres + pgvector.

## Setup

```bash
uv sync                      # Install dependencies
uv run alembic upgrade head  # Run database migrations
```

## Run the Server

```bash
uv run uvicorn app.main:app --reload
```

Runs on `http://localhost:8000`. Health check: `GET /api/v1/health`.

## Tests

```bash
# All backend tests
uv run pytest -q

# Specific test file
uv run pytest tests/test_crawl_seeds.py -v

# Watch mode
uv run pytest -q --tb=short --looponfail
```

Tests include privacy invariants (INV-1 through INV-7) — see [SDD §3](../docs/SDD.md#3-invariants).

## Linting & Format

```bash
# Check style
uv run ruff check .

# Auto-format
uv run ruff format .

# Type check (strict mode on core/ and llm/)
uv run mypy
```

## Database

```bash
# View current schema
psql postgresql://locah:locah@localhost:5432/locah -c "\dt"

# Create a new migration after schema changes
uv run alembic revision --autogenerate -m "description"

# Roll back one migration
uv run alembic downgrade -1
```

Environment: `DATABASE_URL` in `.env` or `backend/.env`.

## Project Structure

- `app/main.py` — FastAPI app entry
- `app/core/config.py` — Settings & environment
- `app/core/redaction.py` — Privacy gate (INV-2)
- `app/ingest/` — Crawler, extractor, chunker, embedder, orchestrator (SDD §5.1). Run the full pipeline: `uv run python -m app.ingest.run`
- `app/llm/` — Model provider integration
- `app/api/` — API routes
- `app/retrieval/` — Knowledge base retrieval
- `migrations/` — Alembic schema versions
- `tests/` — Test suite (privacy invariants)

See [`docs/SDD.md`](../docs/SDD.md) for architecture and invariants.

## Architecture

```mermaid
flowchart TB
  main["app/main.py"]
  api["app/api"]
  core["app/core"]
  ingest["app/ingest"]
  retrieval["app/retrieval"]
  llm["app/llm"]
  db[("Postgres + pgvector")]

  main --> api
  main --> core
  core --> api
  core --> ingest
  api --> ingest
  api --> retrieval
  ingest --> db
  retrieval --> db
  retrieval --> llm
```

`app/ingest` is the offline batch layer — it crawls `wlu.ca`, extracts text, chunks it, and writes dense vector embeddings into `documents` and `chunks`. `app/retrieval` and `app/llm` power the `/ask` endpoint (planned S2), pulling matching chunks from Postgres and synthesising an answer via Claude. `app/core` owns config, redaction, and error types used across everything. `app/api` is HTTP-only: no business logic lives there.

Right now `app/main.py` mounts only the health check and the admin router. Ingest runs through `python -m app.ingest.run` (CLI) or `POST /api/v1/admin/crawl` (background job) — see [`app/ingest/README.md`](app/ingest/README.md).

### Three ways to trigger ingest

```mermaid
flowchart LR
  CLI["uv run python -m app.ingest.run"]
  Admin["POST /api/v1/admin/crawl"]
  GHA["GitHub Actions cron/manual"]

  CLI --> runIngest["run_ingest()"]
  Admin --> startCrawlJob["start_crawl_job()"] --> runIngest
  GHA --> Admin
```
