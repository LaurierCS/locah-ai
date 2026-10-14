"""Integration tests for the ingest pipeline orchestrator (SDD §5.1 / issue #37).

These tests require a live Postgres instance with migrations applied.  They are
automatically skipped when the database is unreachable (e.g. local development
without Docker).  CI always provides Postgres via the ``services:`` block in
``.github/workflows/ci.yml``.

Test doubles follow the same patterns as ``test_embedder.py``: a
``RecordingEncoder`` injects a deterministic mock model so tests run without a
sentence-transformers model download.  768 dimensions are used to match the
``chunks.embedding vector(768)`` schema column.
"""

from __future__ import annotations

import hashlib

from app.ingest.crawler import CrawlResult, persist_crawl_results
from app.ingest.pipeline import IngestSummary, format_ingest_summary, process_crawl_results

# --------------------------------------------------------------------------- #
# Test double: mock embedding encoder
# --------------------------------------------------------------------------- #


class RecordingEncoder:
    """Mock embedding model that tracks calls and returns deterministic vectors.

    Produces 768-dim unit vectors so the pgvector column constraint is satisfied
    without loading the real SentenceTransformer model in CI.
    """

    def __init__(self, dim: int = 768) -> None:
        self.dim = dim
        self.calls = 0

    def __call__(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        # Deterministic per text so repeated calls with the same input agree.
        return [[float(i % self.dim + 1) / self.dim for i in range(self.dim)] for _ in texts]


# --------------------------------------------------------------------------- #
# Shared test data
# --------------------------------------------------------------------------- #

_BODY = (
    "<html><head><title>Tuition Fees</title></head><body><main>"
    "<h1>Tuition Fees</h1>"
    "<p>Full-time students are charged per term. "
    + "Tuition rates are reviewed annually by the Board of Governors. "
    * 20
    + "</p>"
    "<h2 id='payment-deadlines'>Payment Deadlines</h2>"
    "<p>Fall term fees are due in September. "
    + "Late payments incur an administrative fee. " * 20
    + "</p></main></body></html>"
)

_URL = "https://www.wlu.ca/tuition-integration-test"
_CONTENT_HASH = hashlib.sha256(_BODY.encode()).hexdigest()


def _make_result(
    url: str = _URL,
    body: bytes = _BODY.encode(),
    content_hash: str = _CONTENT_HASH,
    content_type: str = "text/html",
) -> CrawlResult:
    """Build a successful CrawlResult for use in pipeline tests."""
    return CrawlResult(
        url=url,
        status="success",
        http_status=200,
        content_hash=content_hash,
        body=body,
        content_type=content_type,
    )


# --------------------------------------------------------------------------- #
# Postgres integration tests
# --------------------------------------------------------------------------- #


async def test_pipeline_embeds_and_is_idempotent(async_session) -> None:
    """First run embeds chunks; second run with the same content_hash is a no-op.

    Acceptance criteria: idempotent second run skips unchanged docs.
    """
    result = _make_result()

    # persist_crawl_results writes the document row that process_crawl_results
    # looks up by URL to obtain the document UUID.
    await persist_crawl_results(async_session, [result], robots_parsers={})

    # --- First run: should produce at least one chunk ---
    encoder1 = RecordingEncoder()
    summary1 = await process_crawl_results(async_session, [result], encoder=encoder1)

    assert summary1.pages_fetched == 1
    assert summary1.chunks_upserted > 0, "First run must persist at least one chunk"
    assert summary1.skipped_unchanged == 0
    assert summary1.errors == 0
    assert encoder1.calls > 0, "First run must call the encoder"

    # --- Second run (identical content_hash): must be a complete no-op ---
    encoder2 = RecordingEncoder()
    summary2 = await process_crawl_results(async_session, [result], encoder=encoder2)

    assert summary2.pages_fetched == 1
    assert summary2.skipped_unchanged == 1, "Unchanged doc must be counted as skipped"
    assert summary2.chunks_upserted == 0
    assert summary2.errors == 0
    assert encoder2.calls == 0, "Second run must not invoke the encoder"


async def test_pipeline_continues_after_extract_failure(async_session) -> None:
    """A bad content-type is skipped; the subsequent good page still gets embedded.

    Acceptance criteria: partial failure is logged and pipeline continues.
    """
    good = _make_result(url="https://www.wlu.ca/good-integration-test")
    bad = _make_result(
        url="https://www.wlu.ca/binary-integration-test",
        body=b"\x00\x01\x02\x03",
        content_hash=hashlib.sha256(b"\x00\x01\x02\x03").hexdigest(),
        content_type="application/octet-stream",  # extract_document returns None for this
    )
    encoder = RecordingEncoder()

    await persist_crawl_results(async_session, [bad, good], robots_parsers={})

    summary = await process_crawl_results(async_session, [bad, good], encoder=encoder)

    assert summary.pages_fetched == 2
    assert summary.extract_skipped == 1, "Bad content-type must be counted as extract_skipped"
    assert summary.chunks_upserted > 0, "Good page must still be embedded"
    assert summary.errors == 0, "No unhandled exceptions expected"


# --------------------------------------------------------------------------- #
# Unit-style tests (no Postgres required)
# --------------------------------------------------------------------------- #


def test_format_ingest_summary_contains_all_fields() -> None:
    """format_ingest_summary output includes every acceptance-criteria field."""
    summary = IngestSummary(
        pages_fetched=5,
        chunks_upserted=42,
        skipped_unchanged=3,
        extract_skipped=1,
        errors=0,
    )
    output = format_ingest_summary(summary)

    assert "Pages fetched" in output
    assert "5" in output
    assert "Chunks upserted" in output
    assert "42" in output
    assert "Skipped unchanged" in output
    assert "3" in output
    assert "Extract skipped" in output
    assert "Errors" in output
