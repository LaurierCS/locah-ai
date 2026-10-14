"""Ingest pipeline orchestrator (SDD §5.1 / issue #37).

Wires crawl → extract → chunk → embed into a single runnable pass with
per-document partial-failure handling and a structured summary.

Public API:
  process_crawl_results  — extract/chunk/embed a list of CrawlResults against a
                           live database; one bad page never aborts the rest.
  run_ingest             — full end-to-end entry point: crawl seeds, persist
                           document rows, then extract/chunk/embed.
  format_ingest_summary  — stable human-readable string for CLI / log output.

Note: the CLI entry point is the minimal ``python -m app.ingest.run``; a Typer
CLI can replace it later if richer subcommands become a requirement (see run.py).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingest.chunk import chunk_extracted_document
from app.ingest.crawler import CrawlResult, crawl
from app.ingest.embed import Encoder, embed_document
from app.ingest.extract import extract_document

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Summary dataclass
# --------------------------------------------------------------------------- #


@dataclass
class IngestSummary:
    """Aggregate counters collected over one full ingest run.

    Attributes:
        pages_fetched:     Pages we attempted to extract/chunk/embed (status="success" with body).
        chunks_upserted:   Total chunk rows written across all newly-embedded pages.
        skipped_unchanged: Pages skipped because content_hash matched embedded_hash.
        extract_skipped:   Pages where extraction produced nothing (unsupported type / empty).
        errors:            Pages that raised an unhandled exception; pipeline continued.
    """

    pages_fetched: int = field(default=0)
    chunks_upserted: int = field(default=0)
    skipped_unchanged: int = field(default=0)
    extract_skipped: int = field(default=0)
    errors: int = field(default=0)


# --------------------------------------------------------------------------- #
# Core orchestration
# --------------------------------------------------------------------------- #


async def process_crawl_results(
    session: AsyncSession,
    results: list[CrawlResult],
    *,
    encoder: Encoder | None = None,
    force: bool = False,
) -> IngestSummary:
    """Extract, chunk, and embed each successful CrawlResult against the database.

    Only processes results where ``status="success"``, ``body`` is non-empty, and
    ``content_hash`` is set (i.e. real 200 fetches, not 304s or errors).

    Each document is wrapped in a try/except so a single page failure never
    aborts the rest.  Exceptions are logged with a full traceback.

    Args:
        session:  SQLAlchemy async session (migrations must be applied).
        results:  CrawlResult list from the crawler — typically ``crawler.results``
                  after ``persist_crawl_results`` has been called so document rows exist.
        encoder:  Optional embedding model override.  When None the real
                  SentenceTransformer model is loaded on first batch call.
        force:    Re-embed even when ``embedded_hash`` already matches ``content_hash``.

    Returns:
        IngestSummary with per-run counters for the CLI / log output.
    """
    summary = IngestSummary()

    for result in results:
        # Only process pages we actually fetched (skip 304 / error / out-of-scope entries).
        if result.status != "success" or not result.body or not result.content_hash:
            continue

        url = result.url
        try:
            summary.pages_fetched += 1

            # --- Extract ---
            extracted = extract_document(
                url=url,
                content_type=result.content_type or "",
                body=result.body,
            )
            if extracted is None:
                logger.warning("Extraction produced nothing for %s — skipping", url)
                summary.extract_skipped += 1
                continue

            # --- Chunk ---
            chunks = chunk_extracted_document(extracted.full_text, extracted.blocks)

            # --- Look up the document row that persist_crawl_results already wrote ---
            row = await session.execute(
                text("SELECT id FROM documents WHERE url = :url"), {"url": url}
            )
            document_id = row.scalar_one_or_none()
            if document_id is None:
                # Should not happen after persist_crawl_results, but guard defensively.
                logger.error("No document row found for %s — skipping embed", url)
                summary.errors += 1
                continue

            # --- Embed + upsert ---
            embed_result = await embed_document(
                session,
                document_id=str(document_id),
                content_hash=result.content_hash,
                chunks=chunks,
                encoder=encoder,
                force=force,
            )

            if embed_result.skipped:
                summary.skipped_unchanged += 1
            else:
                summary.chunks_upserted += embed_result.embedded

        except Exception:
            # Log with traceback so the team can diagnose; pipeline continues.
            logger.exception("Unhandled error while processing %s", url)
            summary.errors += 1

    return summary


async def run_ingest(
    session: AsyncSession,
    *,
    encoder: Encoder | None = None,
    force: bool = False,
) -> IngestSummary:
    """Run the full crawl → extract → chunk → embed pipeline end-to-end.

    Delegates crawling and document persistence to ``crawl()`` (which builds a
    CrawlerConfig from ``settings``), then processes every fetched page through
    ``process_crawl_results``.

    Args:
        session:  SQLAlchemy async session with migrations applied.
        encoder:  Optional embedding model override (primarily useful in tests).
        force:    Forwarded to ``embed_document`` to re-embed unchanged pages.

    Returns:
        IngestSummary with aggregate counters for the run.
    """
    results = await crawl(session)
    return await process_crawl_results(session, results, encoder=encoder, force=force)


# --------------------------------------------------------------------------- #
# Output formatting
# --------------------------------------------------------------------------- #


def format_ingest_summary(summary: IngestSummary) -> str:
    """Return a human-readable multi-line summary of an ingest run.

    Fields match the issue #37 acceptance criteria: pages fetched, chunks
    upserted, skipped unchanged.
    """
    lines = [
        "=== Ingest summary ===",
        f"  Pages fetched:      {summary.pages_fetched}",
        f"  Chunks upserted:    {summary.chunks_upserted}",
        f"  Skipped unchanged:  {summary.skipped_unchanged}",
        f"  Extract skipped:    {summary.extract_skipped}",
        f"  Errors:             {summary.errors}",
    ]
    return "\n".join(lines)
