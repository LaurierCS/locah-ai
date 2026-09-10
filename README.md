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

```bash
cp .env.example .env        # add your ANTHROPIC_API_KEY
docker compose up -d db     # Postgres + pgvector
cd backend && pip install -e ".[dev]" && alembic upgrade head
uvicorn app.main:app --reload
cd ../frontend && npm install && npm run dev
```

Backend on `:8000`, frontend on `:3000`.

## Stack

Python 3.12 · FastAPI · PostgreSQL + pgvector · Anthropic Claude · Next.js 15 · TypeScript · Tailwind

## Status

Semester 1 MVP, in development. See [milestones](docs/SDD.md#11-semester-1-milestones).

## Licence

MIT for our code. Crawled content belongs to Wilfrid Laurier University; we index and quote with attribution and always link to the source.
