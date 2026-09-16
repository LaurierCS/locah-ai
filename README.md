# LOCAH.ai

**Laurier Online Course Agent Helper** — an assistant over Wilfrid Laurier University's *public* information, built by the Laurier Computing Society.

Ask a question, get a plain-language answer with a link to the Laurier page it came from. Where two official pages disagree, LOCAH shows you both. Where Laurier's site doesn't answer, LOCAH says so and tells you who to ask.

## What it does not do

- It does not store your personal information. There are no accounts.
- It does not screen, diagnose, or counsel. It surfaces support Laurier already publishes and connects you to people.
- It does not read your student record. (Degree-audit guidance is a future phase requiring ICT sponsorship and a formal privacy review.)
- It does not send anything to anyone on your behalf.

## Documentation

| Doc | What it's for |
|---|---|
| [Software Design Document](docs/SDD.md) | The engineering contract — architecture, invariants, milestones |
| [Business Requirements](docs/BUSINESS_REQUIREMENTS.md) | Objectives, stakeholders, success measures |
| [Contributing](CONTRIBUTING.md) | How to get set up and merge your first PR |

## Quick start

**Option 1: Full Docker stack (recommended for new contributors)**

```bash
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
docker compose up
```

- Backend on http://localhost:8000
- Frontend on http://localhost:3000
- Database on localhost:5432

See [DOCKER_COMPOSE.md](DOCKER_COMPOSE.md) for other options (database-only, API-only, etc.).

**Option 2: Native tools (for active development)**

Install [uv](https://docs.astral.sh/uv/) and [pnpm](https://pnpm.io/) (Node 24+).

```bash
cp backend/.env.example backend/.env    # add your ANTHROPIC_API_KEY
cp frontend/.env.example frontend/.env  # set BACKEND_URL if needed
docker compose up -d db                 # Postgres + pgvector on :5432

cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload

cd ../frontend
pnpm install
pnpm run dev
```

Backend on `:8000`, frontend on `:3000`. Health check: [http://localhost:8000/api/v1/health](http://localhost:8000/api/v1/health).

## Stack

Python 3.12+ (3.14 via uv) · FastAPI · PostgreSQL + pgvector · Anthropic Claude · Next.js 16 · TypeScript 5 · Tailwind CSS 4 · Node 24 · uv · pnpm

## Status

Semester 1 MVP, in development. See [milestones](docs/SDD.md#11-semester-1-milestones).

## Licence

MIT for our code. Crawled content belongs to Wilfrid Laurier University; we index and quote with attribution and always link to the source.
