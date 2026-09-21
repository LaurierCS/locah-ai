# Docker Compose orchestration

How to run LOCAH.ai's services — the database, the backend API, and the frontend
— with `docker compose`. This covers every service combination, environment-file
setup, the manual migration step required in development, mixing native tools with
containers, and the failures you are most likely to hit.

If any of this doesn't work, that's a bug in our docs — open an issue.

See also: [README.md](README.md) for the quick start, [CONTRIBUTING.md](CONTRIBUTING.md)
for the contribution workflow, and [docs/SDD.md §10 — Deployment](docs/SDD.md#10-deployment) for the
design contract behind this setup.

## Prerequisites

- **Docker Engine** with the Compose V2 plugin (`docker compose`, not the legacy
  `docker-compose`). Docker Desktop on macOS/Windows includes it.
- The Docker **daemon must be running** before any `docker compose` command. On
  Docker Desktop, launch the app and wait until it reports "Engine running"; a stopped
  daemon fails with `failed to connect to the docker API … is the daemon running?`.
- For the **native** paths below: [uv](https://docs.astral.sh/uv/) (backend) and
  [pnpm](https://pnpm.io/) with Node 24+ (frontend).

## Full-stack quick start

These are the exact steps to bring the whole stack (db + api + frontend) up from a
clean checkout. This is the recommended path for new contributors.

```bash
# 1. Make sure the Docker daemon is running (start Docker Desktop and wait for it).

# 2. Create the local env files from the checked-in examples.
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env

# 3. Point the API at the database's in-network hostname.
#    The example ships DATABASE_URL=...@localhost:5432/... which is correct for a
#    NATIVE api. Inside the Docker network the database is the `db` service, so the
#    containerized api needs host `db`, not `localhost`. Edit backend/.env:
#      DATABASE_URL=postgresql+psycopg://locah:locah@db:5432/locah

# 4. Build and start everything (detached).
docker compose up -d --build

# 5. Apply migrations. Compose does NOT auto-migrate in dev (see below), so do it
#    yourself once the db is healthy and the api container is up.
docker compose exec api uv run alembic upgrade head

# 6. Verify.
docker compose ps                                    # all three Up, db "healthy"
curl http://localhost:8000/api/v1/health             # -> {"status":"ok", ...}
curl -o /dev/null -w "%{http_code}\n" http://localhost:3000   # -> 200
```

Then:

- Backend: <http://localhost:8000> (health: <http://localhost:8000/api/v1/health>)
- Frontend: <http://localhost:3000>
- Database: `localhost:5432`

> **Note on `ANTHROPIC_API_KEY`:** the stack boots and health checks pass with an
> empty key, but any actual model call will fail. Add your key to `backend/.env` and
> run `docker compose restart api` when you need answering to work.

## The services

The stack is defined in [`docker-compose.yml`](docker-compose.yml). Three services
share one bridge network (`locah-network`) so they can reach each other by service
name (`db`, `api`, `frontend`).

| Service | Image / build | Host port | Depends on | Notes |
|---|---|---|---|---|
| `db` | `pgvector/pgvector:pg16` | `5432` | — | Postgres 16 with the pgvector extension. Data persists in the `pgdata` named volume. Has a `pg_isready` healthcheck. |
| `api` | builds `./backend` | `8000` | `db` (waits for healthy) | FastAPI via `uv run uvicorn … --reload`. Source is bind-mounted for hot reload. **Does not run migrations** (see below). |
| `frontend` | builds `./frontend` | `3000` | `api` | Next.js dev server via `pnpm run dev`. Source is bind-mounted; `node_modules` and `.next` are kept in the container. |

## Service matrix

`docker compose up <services…>` starts the named services plus anything they depend
on. Because `api` depends on `db`, and `frontend` depends on `api` (which depends on
`db`), naming a higher-level service pulls in the ones below it. Name `db` explicitly
when you want the database on its own.

| Command | Starts | Use it when |
|---|---|---|
| `docker compose up` | `db` + `api` + `frontend` | Full stack. The recommended path for new contributors. |
| `docker compose up db` | `db` only | You run the API and/or frontend natively and just need Postgres. |
| `docker compose up db api` | `db` + `api` | Backend work; frontend run natively or not needed. |
| `docker compose up db frontend` | `db` + `frontend` + `api` | Frontend work against a containerized API. `frontend` depends on `api`, so `api` (and therefore `db`) also starts — you cannot get the frontend container without the API container. |
| `docker compose up api` | `api` + `db` | Same as `db api`; `api`'s dependency pulls in `db`. |
| `docker compose up frontend` | `frontend` + `api` + `db` | Same as the full stack minus nothing meaningful — the whole graph is required. |

Useful flags:

- `-d` — run detached (in the background). `docker compose up -d db` is the usual way
  to start Postgres for native development.
- `--build` — rebuild images before starting, e.g. after changing a `Dockerfile` or
  dependency lockfile.
- `docker compose logs -f api` — follow one service's logs.
- `docker compose down` — stop and remove containers and the network. Add `-v` to also
  delete the `pgdata` volume (wipes the database — see troubleshooting).

## Environment file setup

Both apps read a local, git-ignored `.env`. Create them from the checked-in examples
before starting anything:

```bash
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
```

- **`backend/.env`** — set `ANTHROPIC_API_KEY`. Other keys have working defaults; see
  [`backend/.env.example`](backend/.env.example) for the full list (crawler allowlist,
  retrieval settings, cost cap, etc.).
- **`frontend/.env`** — `BACKEND_URL` defaults to `http://localhost:8000`; leave it for
  local work. See [`frontend/.env.example`](frontend/.env.example).

The compose file loads these with `env_file … required: false`, so the stack will start
without them — but the API won't be able to reach the model provider without a key.

### DATABASE_URL: `localhost` vs `db`

The default `DATABASE_URL` in `backend/.env.example` points at **`localhost:5432`**,
which is correct when the API runs **natively** (on your host, talking to the
port-mapped Postgres).

When the API runs **inside the Docker stack**, `localhost` refers to the API container
itself, not the database. Inside `locah-network` the database is reachable at the
service name **`db`**. If you run the containerized API, set:

```bash
# backend/.env — for the full Docker stack
DATABASE_URL=postgresql+psycopg://locah:locah@db:5432/locah
```

This is the single most common "the API can't connect to the database" cause. See
troubleshooting below.

## Migrations in development (read this)

**`docker compose up api` does not run database migrations.** The backend `Dockerfile`
has a production `CMD` that runs `alembic upgrade head` before starting the server, but
the compose file **overrides that command** with a dev-only `uvicorn --reload` command
that skips migrations. This is deliberate — it keeps reloads fast and avoids surprise
schema changes on every restart — but it means an empty or stale database will cause
the API to error until you migrate it yourself.

Apply migrations manually after the database is up:

**If the API runs in Docker:**

```bash
docker compose up -d db api
docker compose exec api uv run alembic upgrade head
```

(Use `docker compose run --rm api uv run alembic upgrade head` if the `api` container
isn't running yet.)

**If the API runs natively:**

```bash
docker compose up -d db
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

Re-run `alembic upgrade head` whenever you pull changes that add a migration under
`backend/migrations/versions/`, or after creating a new revision. See
[CONTRIBUTING.md](CONTRIBUTING.md) for the schema-change workflow.

## Mixing native tools and containers

The services are decoupled, so you can run any of them natively and the rest in
Docker. Every service reaches the database via port `5432` — published to the host for
native processes, and via the `db` service name inside the network.

Common combinations:

| Setup | Database | API | Frontend | How |
|---|---|---|---|---|
| Full Docker | container | container | container | `docker compose up` (set `DATABASE_URL` host to `db`) |
| Backend dev | container | **native** | container/native | `docker compose up -d db` (+ `frontend`), run API with `uv run uvicorn … --reload` |
| Frontend dev | container | container | **native** | `docker compose up -d db api`, run frontend with `pnpm run dev` |
| Everything native | container | native | native | `docker compose up -d db`, run both apps natively (this is README Option 2) |

Rules of thumb:

- **Database in Docker, everything else negotiable.** Running Postgres+pgvector
  natively is more setup than it's worth; keep it containerized.
- **Pick the right `DATABASE_URL` host.** `localhost` for a native API, `db` for a
  containerized API. Only one `backend/.env` exists, so flip this value when you switch
  the API between native and Docker.
- **Don't double-bind a port.** If Postgres is already running in Docker on `5432`, a
  second native Postgres (or a second `docker compose up db`) will fail to bind. Same
  for `8000` (API) and `3000` (frontend) if you run one both ways.

## Troubleshooting

### Port already in use

Symptom: `Bind for 0.0.0.0:5432 failed: port is already allocated`, or the same for
`8000` / `3000`.

Cause: another process already owns that port — often a local Postgres install, a
previous stack you didn't `down`, or the native version of a service you're also trying
to containerize.

Fix:

```bash
# Find what's holding the port (5432 shown; swap for 8000 or 3000)
lsof -i :5432                 # macOS/Linux
# or
docker compose ps            # is a previous stack still up?

docker compose down          # stop a leftover stack cleanly
```

Then either stop the conflicting process, or remap the host port in
`docker-compose.yml` (e.g. `"5433:5432"`) and update `DATABASE_URL` to match.

### pgvector: "extension \"vector\" does not exist" / vector type errors

Symptom: migrations or queries fail with `type "vector" does not exist` or
`could not open extension control file … vector`.

Causes and fixes:

- **Wrong image.** The extension only ships in the `pgvector/pgvector:*` image. If you
  pointed `db` at a plain `postgres` image, switch it back to
  `pgvector/pgvector:pg16` and recreate the container.
- **Extension not created.** The `CREATE EXTENSION vector` should live in the initial
  Alembic migration. If you connected to a database that was never migrated, run
  `alembic upgrade head` (see the migrations section) — remember the API container does
  **not** do this for you.
- **Stale volume from a non-pgvector image.** If you first started `db` on a plain
  Postgres image, the `pgdata` volume is initialized without pgvector. Reset it:

  ```bash
  docker compose down -v      # deletes the pgdata volume — destroys all local data
  docker compose up -d db
  # then re-run migrations
  ```

### API can't connect to the database

Symptom: `connection refused` / `could not translate host name "db"` /
`Connection refused (localhost:5432)` in the API logs.

Fixes:

- **Containerized API:** `DATABASE_URL` host must be `db`, not `localhost`
  (see [DATABASE_URL: `localhost` vs `db`](#database_url-localhost-vs-db)).
- **Native API:** the host must be `localhost` and `db` must be up and port-mapped
  (`docker compose up -d db`).
- **Database not healthy yet:** the `api` service waits for the `db` healthcheck, but a
  native API started too early will fail. Check `docker compose ps` shows `db` as
  `healthy` first.

### Migrations "did nothing" or the schema looks wrong

You probably relied on `docker compose up api` to migrate. It doesn't. Run
`alembic upgrade head` yourself — see [Migrations in development](#migrations-in-development-read-this).

### Frontend can't reach the API

- **Frontend in Docker:** it talks to the API via `BACKEND_URL=http://api:8000`, which
  the compose file sets on the `frontend` service. Make sure `api` is actually running.
- **Frontend native, API in Docker:** `BACKEND_URL` should be `http://localhost:8000`
  (the default) so it uses the host-published port.

### Changes to dependencies aren't picked up

Editing `pyproject.toml`/`uv.lock` or `package.json`/`pnpm-lock.yaml` requires an image
rebuild — the bind mount only covers source, not installed packages:

```bash
docker compose up --build api        # or frontend
```
