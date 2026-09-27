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
- `app/ingest/` — Crawler, extractor, chunker, embedder (SDD §5.1)
- `app/llm/` — Model provider integration
- `app/api/` — API routes
- `app/retrieval/` — Knowledge base retrieval
- `migrations/` — Alembic schema versions
- `tests/` — Test suite (privacy invariants)

See [`docs/SDD.md`](../docs/SDD.md) for architecture and invariants.
