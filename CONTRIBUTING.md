# Contributing to LOCAH.ai

## Before your first PR

1. Read [docs/SDD.md §3 — Invariants](docs/SDD.md#3-invariants). They are non-negotiable. A PR that weakens one is rejected regardless of how good the rest is.
2. Find your pod in [SDD §4.3](docs/SDD.md#43-team-decomposition-10-volunteers-5-pods). You own a directory.
3. Get the stack running locally. See [README.md](README.md) for Docker or native setup. See [DOCKER_COMPOSE.md](DOCKER_COMPOSE.md) for orchestration options. If it doesn't work, that's a bug in our docs — open an issue.

## Workflow

- Branch from `main`: `feat/<pod>-<short-description>` or `fix/...`.
- Small PRs. One reviewer from your pod, one from Platform for anything touching `app/core/` or the schema.
- CI must be green: lint, typecheck, and unit tests. The eval smoke set gates PRs once the harness exists (S3).
- Conventional commits: `feat(ingest): heading-aware chunker`.

## Tooling

- Backend: `uv sync` then `uv run pytest`, `uv run ruff check .`, `uv run mypy`.
- Frontend: `pnpm install` then `pnpm run lint`, `pnpm run typecheck`.
- Full ingest pipeline: `cd backend && uv run python -m app.ingest.run` (see [backend/app/ingest/README.md](backend/app/ingest/README.md)).
- Schema changes: Alembic revision under `backend/migrations/versions/`. Apply with `uv run alembic upgrade head`.

## Scheduled crawls

The [crawl workflow](.github/workflows/crawl.yml) calls the staging backend's
`POST /api/v1/admin/crawl` endpoint. Configure these secrets in the GitHub
repository's **staging** environment before enabling scheduled or manual runs:

- `BACKEND_URL` — public base URL of the staging backend, without `/api/v1`.
- `ADMIN_TOKEN` — bearer token matching the staging backend's `ADMIN_TOKEN`.

### Obtain and configure the values

1. Deploy the backend to the staging service (the [deployment design](docs/SDD.md#10-deployment)
   proposes Railway or Fly.io). Copy its **public HTTPS base URL** from that
   service's dashboard, for example `https://api-staging.example.org`. Confirm
   that `<base URL>/api/v1/health` responds. Use this base URL as `BACKEND_URL`;
   a local address such as `localhost:8000` or Docker's `api:8000` is not
   reachable from a GitHub-hosted runner. The repo does not currently record an
   actual staging URL.
2. Generate a random token on your own machine with
   `python -c "import secrets; print(secrets.token_urlsafe(32))"`. Set the
   generated value as `ADMIN_TOKEN` in the **staging backend service's**
   environment variables. Set the exact same value as the `ADMIN_TOKEN` secret
   in GitHub's **staging** environment. Never add the value to this repo or a
   documentation file. The backend's settings already read `ADMIN_TOKEN` from
   the environment (`backend/app/core/config.py`).
3. In the GitHub repository, open **Settings → Environments → staging →
   Environment secrets** and add `BACKEND_URL` and `ADMIN_TOKEN`. The workflow
   references the `staging` environment, so those secrets are available to its
   job. Only a repository administrator can configure environment secrets for
   an organization repository. See [GitHub's environment-secret instructions](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets#creating-secrets-for-an-environment).
4. The `POST /api/v1/admin/crawl` route (issue #38, shipped) is a URL path on the
   backend, not a third secret or a separate service. It verifies
   `Authorization: Bearer <ADMIN_TOKEN>` and returns 2xx once a background job is
   accepted. The workflow may send `full` or `high_churn` in the JSON body; honoring
   that scope is [issue #100](https://github.com/LaurierCS/locah-ai/issues/100) — today
   both run a full ingest. Check `<base URL>/openapi.json` without starting a crawl.
   Do not run a crawl until issue #1's ICT signoff.

In **Actions → Crawl staging knowledge base → Run workflow**, choose `full`
or `high_churn` to start a manual pass. The workflow checks only whether the
backend accepted the request; the crawl continues on the backend. A non-2xx
response fails the workflow. The workflow sends
`{"scope":"full"}` or `{"scope":"high_churn"}`; the backend ignores scope until
[#100](https://github.com/LaurierCS/locah-ai/issues/100).

## The rules that get PRs rejected

- Adding a code path by which the safety classifier can downrank, suppress, or auto-resolve anything (**INV-5**).
- Sending text to the model provider without passing through `app/core/redaction.py` (**INV-2**).
- Persisting anything that links a question to a person (**INV-3**).
- An answer path that can emit a factual claim with no citation (**INV-4**).
- Secrets in the repo. Ever.

## Code style

Python: ruff + mypy strict on `app/core` and `app/llm`. TypeScript: eslint + `tsc --noEmit`. Format on save.

Every module gets a `README.md` explaining what it does and who owns it. If your successor next year can't understand it, it isn't finished.
