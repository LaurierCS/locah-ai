# Alembic

Schema lives in `versions/`. Generate a new revision with:

```bash
uv run alembic revision -m "describe the change"
```

Apply with `uv run alembic upgrade head`. Source of truth is the Python revisions, not a separate SQL dump. Spec: [SDD §6](../../docs/SDD.md#6-data-model).

## CI/CD Integration

Migrations are automatically run on every PR and push to main before tests execute. This ensures:

- Migration SQL syntax is valid against pgvector Postgres
- Database schema matches migration files before running tests
- Any broken migrations are caught immediately in CI
