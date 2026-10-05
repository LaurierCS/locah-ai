# API routers — Platform pod

HTTP only, no business logic. Routes are declared here and call into ingest, retrieval, llm, and analytics.

Live routes: `GET /api/v1/health` (still in `app/main.py`) and `POST /api/v1/admin/crawl` (`admin.py`). Move the rest here as `/ask`, `/trends`, and `/conflicts` land.

Contract: [SDD §7](../../../docs/SDD.md#7-api-contract). Errors are RFC 7807 `application/problem+json` (`app/core/errors.py`).

Swagger UI is at `/docs` (`docs.py`). It is the stock Swagger page with the padlock icons hidden, because Swagger never validates the token and the icon flips as soon as anything is typed into Authorize. Only the 202/401 response tells you whether a token works.

## `POST /api/v1/admin/crawl`

Triggers the ingest pipeline (`run_ingest` in [`app/ingest/pipeline.py`](../ingest/pipeline.py)) for CI/cron and manual ops. Auth is `Authorization: Bearer <ADMIN_TOKEN>`; an unset `ADMIN_TOKEN` disables the endpoint (every request gets 401).

| Status | Meaning |
|---|---|
| `202` | Job started in the background. Body: `{job_id, status: "running", started_at, finished_at, summary, error}` |
| `401` | Missing/invalid token, or `ADMIN_TOKEN` unset |
| `409` | A crawl is already running; the running job is in the `job` member of the problem body |

```bash
curl -X POST http://localhost:8000/api/v1/admin/crawl -H "Authorization: Bearer $ADMIN_TOKEN"
```

Job state lives in `app/ingest/jobs.py`: in memory, one job at a time, and per-process, so run a single API worker. There is no polling route yet; follow progress and the final summary in the API logs. Failure details are logged, never returned.
