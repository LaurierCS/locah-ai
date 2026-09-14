# Backend — Platform pod

Python 3.12+ (3.14 locally via uv), FastAPI, Alembic, Postgres + pgvector.

```bash
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

Health: `GET /api/v1/health`. Remaining routes land in later sprints — see [SDD §7](../docs/SDD.md#7-api-contract).
