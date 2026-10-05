"""Background crawl jobs for the admin endpoint (SDD §7 / issue #38).

Runs the ingest pipeline (``pipeline.run_ingest``) as an in-process asyncio task and
tracks one job at a time. State is per-process, so this assumes a single API worker.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import settings

if TYPE_CHECKING:
    from app.ingest.pipeline import IngestSummary

logger = logging.getLogger(__name__)

JobStatus = Literal["running", "succeeded", "failed"]


@dataclass
class CrawlJob:
    job_id: str
    status: JobStatus
    started_at: datetime
    finished_at: datetime | None = None
    summary: dict[str, int] | None = None
    # Deliberately generic: details stay in the server logs.
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "summary": self.summary,
            "error": self.error,
        }


class CrawlAlreadyRunning(Exception):
    def __init__(self, job: CrawlJob) -> None:
        super().__init__(job.job_id)
        self.job = job


async def _execute() -> IngestSummary:
    """Run the full pipeline on its own engine/session (the request session is gone by now)."""
    # Deferred: the pipeline pulls in trafilatura/pypdf, which the API doesn't need until a crawl.
    from app.ingest.pipeline import run_ingest

    engine = create_async_engine(settings.database_url, echo=False)
    try:
        async with AsyncSession(engine) as session:
            return await run_ingest(session)
    finally:
        await engine.dispose()


_current: CrawlJob | None = None
_task: asyncio.Task[None] | None = None  # strong reference so the task isn't garbage collected


async def _run(job: CrawlJob) -> None:
    try:
        from app.ingest.pipeline import format_ingest_summary

        summary = await _execute()
        job.summary = asdict(summary)
        job.status = "succeeded"
        logger.info("Crawl job %s finished: %s", job.job_id, format_ingest_summary(summary))
    except Exception:
        logger.exception("Crawl job %s failed", job.job_id)
        job.status = "failed"
        job.error = "Ingest run failed; see server logs."
    finally:
        job.finished_at = datetime.now(UTC)


def start_crawl_job() -> CrawlJob:
    """Start a crawl job, or raise ``CrawlAlreadyRunning`` if one is in progress."""
    global _current, _task
    if _current is not None and _current.status == "running":
        raise CrawlAlreadyRunning(_current)
    job = CrawlJob(job_id=str(uuid.uuid4()), status="running", started_at=datetime.now(UTC))
    _current = job
    _task = asyncio.create_task(_run(job))
    return job


async def wait_for_current_job() -> None:
    """Await the in-flight job, if any (used by tests)."""
    if _task is not None:
        await _task


def reset_jobs() -> None:
    """Forget job state (used by tests)."""
    global _current, _task
    _current = None
    _task = None
