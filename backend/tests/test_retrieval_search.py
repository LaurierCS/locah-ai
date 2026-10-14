"""Hybrid search integration tests (SDD §5.2 / issue #7).

Requires live Postgres with migrations applied; skipped via async_session when
the DB is unreachable. Encoders are injected — no SentenceTransformer in CI.
"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingest.embed import vector_to_pg_literal
from app.retrieval.search import hybrid_search

_DIM = 768


class FixedEncoder:
    """Returns the same vector for every text (query-time dense control)."""

    def __init__(self, vector: list[float]) -> None:
        self.vector = vector
        self.calls: list[list[str]] = []

    def __call__(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [list(self.vector) for _ in texts]


def _unit(index: int) -> list[float]:
    vec = [0.0] * _DIM
    vec[index] = 1.0
    return vec


_INSERT_DOC = text(
    """
    INSERT INTO documents (id, url, title, content_hash, is_active)
    VALUES (:id, :url, :title, :content_hash, :is_active)
    """
)
_INSERT_CHUNK = text(
    """
    INSERT INTO chunks (id, document_id, ordinal, heading_path, text, token_count,
                        url_anchor, embedding)
    VALUES (:id, :document_id, :ordinal, :heading_path, :text, :token_count,
            :url_anchor, CAST(:embedding AS vector))
    """
)


async def _seed(
    session: AsyncSession,
    *,
    url: str,
    title: str,
    chunks: list[tuple[str, str, list[float] | None]],
    is_active: bool = True,
) -> list[str]:
    """Insert one document and chunks. `chunks` is (chunk_id, text, embedding)."""
    doc_id = str(uuid4())
    await session.execute(
        _INSERT_DOC,
        {
            "id": doc_id,
            "url": url,
            "title": title,
            "content_hash": "test-hash",
            "is_active": is_active,
        },
    )
    ids: list[str] = []
    for ordinal, (chunk_id, body, embedding) in enumerate(chunks):
        ids.append(chunk_id)
        params = {
            "id": chunk_id,
            "document_id": doc_id,
            "ordinal": ordinal,
            "heading_path": "Test",
            "text": body,
            "token_count": 12,
            "url_anchor": None,
            "embedding": vector_to_pg_literal(embedding) if embedding is not None else None,
        }
        if embedding is None:
            await session.execute(
                text(
                    """
                    INSERT INTO chunks (id, document_id, ordinal, heading_path, text,
                                        token_count, url_anchor, embedding)
                    VALUES (:id, :document_id, :ordinal, :heading_path, :text,
                            :token_count, :url_anchor, NULL)
                    """
                ),
                {k: v for k, v in params.items() if k != "embedding"},
            )
        else:
            await session.execute(_INSERT_CHUNK, params)
    await session.commit()
    return ids


async def test_empty_question_returns_empty(async_session: AsyncSession) -> None:
    hits = await hybrid_search(async_session, "   ", encoder=FixedEncoder(_unit(0)))
    assert hits == []


async def test_sparse_leg_finds_course_code(async_session: AsyncSession) -> None:
    id_a, id_b = str(uuid4()), str(uuid4())
    await _seed(
        async_session,
        url="https://www.wlu.ca/cs",
        title="CS",
        chunks=[
            (id_a, "Students in CP104 write programs in Python at Laurier.", _unit(0)),
            (id_b, "Parking permits are sold at the Welcome Centre desk.", _unit(1)),
        ],
    )
    hits = await hybrid_search(async_session, "CP104", encoder=FixedEncoder(_unit(1)), top_k=8)
    ids = [h.chunk_id for h in hits]
    assert id_a in ids
    matched = next(h for h in hits if h.chunk_id == id_a)
    assert matched.sparse_rank == 1
    assert matched.sparse_score is not None and matched.sparse_score > 0


async def test_dense_leg_ranks_matching_vector_first(async_session: AsyncSession) -> None:
    id_a, id_b = str(uuid4()), str(uuid4())
    await _seed(
        async_session,
        url="https://www.wlu.ca/dense",
        title="Dense",
        chunks=[
            (id_a, "Generic advising office hours are posted online.", _unit(0)),
            (id_b, "Unrelated fluff about campus maps and buildings.", _unit(1)),
        ],
    )
    # Query text will not FTS-match; dense should still surface id_a.
    hits = await hybrid_search(
        async_session, "zzzznotatoken", encoder=FixedEncoder(_unit(0)), top_k=8
    )
    assert hits[0].chunk_id == id_a
    assert hits[0].dense_rank == 1
    assert hits[0].dense_distance is not None
    assert hits[0].dense_distance < 1e-6
    assert hits[0].sparse_rank is None


async def test_rrf_fuses_both_legs(async_session: AsyncSession) -> None:
    id_a, id_b = str(uuid4()), str(uuid4())
    await _seed(
        async_session,
        url="https://www.wlu.ca/coop",
        title="Co-op",
        chunks=[
            (id_a, "The CP104 course is required before applying to co-op.", _unit(0)),
            (id_b, "Parking permits are sold at the Welcome Centre desk.", _unit(1)),
        ],
    )
    # Sparse: A (CP104). Dense query vector = B. A is on both lists (dense #2).
    hits = await hybrid_search(async_session, "CP104", encoder=FixedEncoder(_unit(1)), top_k=8)
    assert {h.chunk_id for h in hits} >= {id_a, id_b}
    assert hits[0].chunk_id == id_a
    assert hits[0].sparse_rank == 1
    assert hits[0].dense_rank == 2
    b = next(h for h in hits if h.chunk_id == id_b)
    assert b.dense_rank == 1
    assert hits[0].rrf_score > b.rrf_score
    assert [h.rank for h in hits] == list(range(1, len(hits) + 1))


async def test_inactive_documents_are_excluded(async_session: AsyncSession) -> None:
    active_id, inactive_id = str(uuid4()), str(uuid4())
    await _seed(
        async_session,
        url="https://www.wlu.ca/active",
        title="Active",
        chunks=[(active_id, "CP104 is listed on the active calendar page.", _unit(0))],
        is_active=True,
    )
    await _seed(
        async_session,
        url="https://www.wlu.ca/retired",
        title="Retired",
        chunks=[(inactive_id, "CP104 appears only on a retired draft page.", _unit(0))],
        is_active=False,
    )
    hits = await hybrid_search(async_session, "CP104", encoder=FixedEncoder(_unit(0)), top_k=8)
    ids = {h.chunk_id for h in hits}
    assert active_id in ids
    assert inactive_id not in ids
