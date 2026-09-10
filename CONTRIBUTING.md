# Contributing to LOCAH.ai

## Before your first PR

1. Read [docs/SDD.md §3 — Invariants](docs/SDD.md#3-invariants). They are non-negotiable. A PR that weakens one is rejected regardless of how good the rest is.
2. Find your pod in [SDD §4.3](docs/SDD.md#43-team-decomposition-10-volunteers-5-pods). You own a directory.
3. Get the stack running locally (see README). If it doesn't work, that's a bug in our docs — open an issue.

## Workflow

- Branch from `main`: `feat/<pod>-<short-description>` or `fix/...`.
- Small PRs. One reviewer from your pod, one from Platform for anything touching `core/` or the schema.
- CI must be green: lint, typecheck, tests, and the eval smoke set.
- Conventional commits: `feat(ingest): heading-aware chunker`.

## The rules that get PRs rejected

- Adding a code path by which the safety classifier can downrank, suppress, or auto-resolve anything (**INV-5**).
- Sending text to the model provider without passing through `core/redaction.py` (**INV-2**).
- Persisting anything that links a question to a person (**INV-3**).
- An answer path that can emit a factual claim with no citation (**INV-4**).
- Secrets in the repo. Ever.

## Code style

Python: ruff + mypy strict on `app/core` and `app/llm`. TypeScript: eslint + `tsc --noEmit`. Format on save.

Every module gets a `README.md` explaining what it does and who owns it. If your successor next year can't understand it, it isn't finished.
