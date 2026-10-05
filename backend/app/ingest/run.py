"""CLI entry point for the ingest pipeline (SDD §5.1 / issue #37).

Run from the backend directory::

    uv run python -m app.ingest.run [--force]

``DATABASE_URL`` is read from the environment or from ``backend/.env`` /
``.env`` at the repo root via ``app.core.config.settings``.  Run migrations
first if the schema is not yet applied::

    uv run alembic upgrade head

This is a minimal ``asyncio``-based entry point.  If a richer CLI with
subcommands or structured ``--help`` output becomes a requirement, replace
``argparse`` here with `Typer <https://typer.tiangolo.com/>`_ (add
``typer[all]`` to ``pyproject.toml`` dependencies first).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import settings
from app.ingest.pipeline import format_ingest_summary, run_ingest

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)


async def _run(*, force: bool) -> None:
    """Create an engine, run the full pipeline, print the summary."""
    engine = create_async_engine(settings.database_url, echo=False)
    try:
        async with AsyncSession(engine) as session:
            logger.info("Starting ingest pipeline (force=%s)", force)
            summary = await run_ingest(session, force=force)
    finally:
        await engine.dispose()

    # Summary goes to stdout so it can be captured separately from logs.
    print(format_ingest_summary(summary))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="python -m app.ingest.run",
        description="Run the LOCAH.ai ingest pipeline: crawl → extract → chunk → embed.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-embed all pages even when their content hash is unchanged.",
    )
    args = parser.parse_args()
    asyncio.run(_run(force=args.force))
