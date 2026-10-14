"""Embedder tests (SDD §5.1 / issue #35).

No live model and no live database: the embedding model is injected as a mock
encoder, and the database session is a lightweight fake. This keeps CI free of
model downloads and Postgres (per the issue's "mocked embedding API" criterion).
"""

from __future__ import annotations

import pytest

from app.ingest.chunk import Chunk
from app.ingest.embed import EmbedResult, embed_document, embed_texts


# --------------------------------------------------------------------------- #
# Test doubles
# --------------------------------------------------------------------------- #
class RecordingEncoder:
    """Mock embedding model. Records the batches it was asked to encode and
    returns a deterministic fixed-dimension vector per text."""

    def __init__(self, dim: int = 4) -> None:
        self.dim = dim
        self.batches: list[list[str]] = []
        self.calls = 0

    def __call__(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        self.batches.append(list(texts))
        return [[float(len(t))] * self.dim for t in texts]


class FlakyEncoder:
    """Fails the first `fail_times` calls, then succeeds. Exercises backoff."""

    def __init__(self, fail_times: int, dim: int = 4) -> None:
        self.fail_times = fail_times
        self.dim = dim
        self.calls = 0

    def __call__(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("transient embedding failure")
        return [[1.0] * self.dim for _ in texts]


class FakeResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object:
        return self._value


class FakeSession:
    """Minimal stand-in for sqlalchemy.ext.asyncio.AsyncSession.

    Records (sql, params) for every execute and answers the embedded_hash
    lookup with whatever was seeded in the constructor.
    """

    def __init__(self, embedded_hash: str | None = None) -> None:
        self._embedded_hash = embedded_hash
        self.executed: list[tuple[str, dict | None]] = []
        self.committed = False

    async def execute(self, statement: object, params: dict | None = None) -> FakeResult:
        sql = str(statement)
        self.executed.append((sql, params))
        if "SELECT embedded_hash" in sql:
            return FakeResult(self._embedded_hash)
        return FakeResult(None)

    async def commit(self) -> None:
        self.committed = True

    # Convenience accessors for assertions
    def inserts(self) -> list[dict]:
        return [p for sql, p in self.executed if "INSERT INTO chunks" in sql and p]

    def updated_hash(self) -> str | None:
        for sql, p in self.executed:
            if "UPDATE documents" in sql and p:
                return p.get("embedded_hash")
        return None


def make_chunks(n: int) -> list[Chunk]:
    return [
        Chunk(
            text=f"passage number {i} with enough words to look real",
            heading_path=f"Section {i}",
            char_start=i * 10,
            char_end=i * 10 + 9,
            url_anchor=f"sec-{i}" if i % 2 == 0 else None,
            token_count=8,
        )
        for i in range(n)
    ]


# --------------------------------------------------------------------------- #
# embed_texts: batching + retry/backoff (pure, synchronous core)
# --------------------------------------------------------------------------- #
def test_embed_texts_returns_one_vector_per_text() -> None:
    enc = RecordingEncoder(dim=3)
    vectors = embed_texts(["a", "bb", "ccc"], encoder=enc)
    assert len(vectors) == 3
    assert all(len(v) == 3 for v in vectors)


def test_embed_texts_batches_by_batch_size() -> None:
    enc = RecordingEncoder()
    texts = [f"t{i}" for i in range(70)]
    embed_texts(texts, encoder=enc, batch_size=32)
    # 70 items at batch_size 32 -> batches of 32, 32, 6
    assert [len(b) for b in enc.batches] == [32, 32, 6]


def test_embed_texts_empty_input_makes_no_calls() -> None:
    enc = RecordingEncoder()
    assert embed_texts([], encoder=enc) == []
    assert enc.calls == 0


def test_embed_texts_retries_then_succeeds_with_exponential_backoff() -> None:
    enc = FlakyEncoder(fail_times=2)
    delays: list[float] = []
    vectors = embed_texts(
        ["a", "b"],
        encoder=enc,
        max_retries=3,
        backoff_base=0.5,
        sleep=delays.append,
    )
    assert len(vectors) == 2
    assert enc.calls == 3  # 2 failures + 1 success
    # Exponential: base * 2**0, base * 2**1
    assert delays == [0.5, 1.0]


def test_embed_texts_raises_after_exhausting_retries() -> None:
    enc = FlakyEncoder(fail_times=99)
    with pytest.raises(RuntimeError, match="transient embedding failure"):
        embed_texts(["a"], encoder=enc, max_retries=2, backoff_base=0.0, sleep=lambda _s: None)


# --------------------------------------------------------------------------- #
# embed_document: skip-unchanged, upsert, hash bookkeeping
# --------------------------------------------------------------------------- #
async def test_skips_when_content_hash_unchanged() -> None:
    enc = RecordingEncoder()
    session = FakeSession(embedded_hash="abc123")
    result = embed_document(
        session, document_id="doc-1", content_hash="abc123", chunks=make_chunks(3), encoder=enc
    )
    result = await result
    assert result == EmbedResult(document_id="doc-1", embedded=0, skipped=True)
    assert enc.calls == 0
    assert session.inserts() == []
    assert not session.committed


async def test_embeds_when_hash_changed() -> None:
    enc = RecordingEncoder()
    session = FakeSession(embedded_hash="old")
    result = await embed_document(
        session, document_id="doc-1", content_hash="new", chunks=make_chunks(3), encoder=enc
    )
    assert result.skipped is False
    assert result.embedded == 3
    assert enc.calls == 1
    assert len(session.inserts()) == 3
    assert session.updated_hash() == "new"
    assert session.committed


async def test_embeds_when_no_prior_hash() -> None:
    enc = RecordingEncoder()
    session = FakeSession(embedded_hash=None)
    result = await embed_document(
        session, document_id="doc-1", content_hash="first", chunks=make_chunks(2), encoder=enc
    )
    assert result.embedded == 2
    assert enc.calls == 1


async def test_force_reembeds_even_when_hash_matches() -> None:
    enc = RecordingEncoder()
    session = FakeSession(embedded_hash="same")
    result = await embed_document(
        session,
        document_id="doc-1",
        content_hash="same",
        chunks=make_chunks(2),
        encoder=enc,
        force=True,
    )
    assert result.skipped is False
    assert enc.calls == 1


async def test_upsert_params_carry_ordinal_and_embedding() -> None:
    enc = RecordingEncoder(dim=4)
    session = FakeSession()
    await embed_document(
        session, document_id="doc-9", content_hash="h", chunks=make_chunks(2), encoder=enc
    )
    inserts = session.inserts()
    assert [p["ordinal"] for p in inserts] == [0, 1]
    assert all(p["document_id"] == "doc-9" for p in inserts)
    # Embedding is passed as a pgvector string literal, e.g. "[48.0,48.0,48.0,48.0]"
    first = inserts[0]
    assert first["embedding"].startswith("[") and first["embedding"].endswith("]")
    assert first["embedding"].count(",") == 3  # dim=4 -> 3 commas


async def test_empty_chunks_still_records_hash_and_clears() -> None:
    enc = RecordingEncoder()
    session = FakeSession(embedded_hash="old")
    result = await embed_document(
        session, document_id="doc-1", content_hash="new", chunks=[], encoder=enc
    )
    assert result.embedded == 0
    assert result.skipped is False
    assert enc.calls == 0
    assert session.updated_hash() == "new"
    assert session.committed
