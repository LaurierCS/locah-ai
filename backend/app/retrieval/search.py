"""Hybrid search: dense pgvector + sparse FTS, fused with RRF (SDD §5.2 / #7).

INV-7 confidence scoring lives in retrieval/confidence.py (#9 — implemented).
    Pass the returned list directly to assess_confidence; do not re-query Postgres.
TODO(#11): retrieval/conflict.py runs on this fused top-k, not on raw legs.
TODO(#72): ask pipeline calls hybrid_search then passes chunks to llm/answer.py.
TODO(#73): FastAPI /ask must wrap query embed_texts in asyncio.to_thread so
    the event loop is not blocked (see ingest/embed.py module docstring).
TODO(#33): manual smoke against a real wlu.ca index (≥2k chunks) is not a
    merge blocker for #7; required before closing parent epic #68.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.ingest.embed import Encoder, embed_texts, vector_to_pg_literal
from app.retrieval.rrf import DEFAULT_RRF_K, fused_ranking, reciprocal_rank_fusion
from app.retrieval.types import RetrievedChunk

# SDD §5.2: candidate lists before fusion; trim uses settings.retrieval_top_k.
DENSE_CANDIDATE_K = 30
SPARSE_CANDIDATE_K = 30
RRF_K = DEFAULT_RRF_K

_DENSE_SQL = text(
    """
    SELECT c.id, c.document_id, c.ordinal, c.text, c.heading_path, c.url_anchor,
           d.url, d.title,
           (c.embedding <=> CAST(:query_vec AS vector)) AS dense_distance
    FROM chunks c
    JOIN documents d ON d.id = c.document_id
    WHERE d.is_active AND c.embedding IS NOT NULL
    ORDER BY dense_distance ASC
    LIMIT :dense_k
    """
)

_SPARSE_SQL = text(
    """
    SELECT c.id, c.document_id, c.ordinal, c.text, c.heading_path, c.url_anchor,
           d.url, d.title,
           ts_rank_cd(c.tsv, plainto_tsquery('english', :query_text)) AS sparse_score
    FROM chunks c
    JOIN documents d ON d.id = c.document_id
    WHERE d.is_active
      AND c.tsv @@ plainto_tsquery('english', :query_text)
    ORDER BY sparse_score DESC
    LIMIT :sparse_k
    """
)


@dataclass
class _Candidate:
    chunk_id: str
    document_id: str
    ordinal: int
    url: str
    title: str | None
    text: str
    heading_path: str | None
    url_anchor: str | None
    dense_rank: int | None = None
    dense_distance: float | None = None
    sparse_rank: int | None = None
    sparse_score: float | None = None


def _as_id(value: Any) -> str:
    if isinstance(value, UUID):
        return str(value)
    return str(value)


def _row_to_candidate(row: Any) -> _Candidate:
    mapping = row._mapping  # sqlalchemy Row
    title = mapping["title"]
    heading = mapping["heading_path"]
    anchor = mapping["url_anchor"]
    return _Candidate(
        chunk_id=_as_id(mapping["id"]),
        document_id=_as_id(mapping["document_id"]),
        ordinal=int(mapping["ordinal"]),
        url=str(mapping["url"]),
        title=None if title is None else str(title),
        text=str(mapping["text"]),
        heading_path=None if heading is None else str(heading),
        url_anchor=None if anchor is None else str(anchor),
    )


def _merge_candidate(store: dict[str, _Candidate], incoming: _Candidate) -> _Candidate:
    existing = store.get(incoming.chunk_id)
    if existing is None:
        store[incoming.chunk_id] = incoming
        return incoming
    if incoming.dense_rank is not None:
        existing.dense_rank = incoming.dense_rank
        existing.dense_distance = incoming.dense_distance
    if incoming.sparse_rank is not None:
        existing.sparse_rank = incoming.sparse_rank
        existing.sparse_score = incoming.sparse_score
    return existing


async def hybrid_search(
    session: AsyncSession,
    question: str,
    *,
    encoder: Encoder | None = None,
    top_k: int | None = None,
) -> list[RetrievedChunk]:
    """Retrieve fused top-k chunks for `question`.

    `encoder` is injectable so CI never downloads SentenceTransformer.
    `top_k` defaults to settings.retrieval_top_k (8).
    """
    query = question.strip()
    if not query:
        return []

    limit = settings.retrieval_top_k if top_k is None else top_k

    query_vec = embed_texts([query], encoder=encoder)[0]
    dense_result = await session.execute(
        _DENSE_SQL,
        {"query_vec": vector_to_pg_literal(query_vec), "dense_k": DENSE_CANDIDATE_K},
    )
    sparse_result = await session.execute(
        _SPARSE_SQL,
        {"query_text": query, "sparse_k": SPARSE_CANDIDATE_K},
    )

    store: dict[str, _Candidate] = {}
    dense_ids: list[str] = []
    for rank, row in enumerate(dense_result, start=1):
        cand = _row_to_candidate(row)
        cand.dense_rank = rank
        cand.dense_distance = float(row._mapping["dense_distance"])
        _merge_candidate(store, cand)
        dense_ids.append(cand.chunk_id)

    sparse_ids: list[str] = []
    for rank, row in enumerate(sparse_result, start=1):
        cand = _row_to_candidate(row)
        cand.sparse_rank = rank
        cand.sparse_score = float(row._mapping["sparse_score"])
        _merge_candidate(store, cand)
        sparse_ids.append(cand.chunk_id)

    scores = reciprocal_rank_fusion(dense_ids, sparse_ids, k=RRF_K)
    ranked = fused_ranking(scores)[:limit]

    hits: list[RetrievedChunk] = []
    for fused_rank, (chunk_id, rrf_score) in enumerate(ranked, start=1):
        cand = store[chunk_id]
        hits.append(
            RetrievedChunk(
                chunk_id=cand.chunk_id,
                document_id=cand.document_id,
                ordinal=cand.ordinal,
                url=cand.url,
                title=cand.title,
                text=cand.text,
                heading_path=cand.heading_path,
                url_anchor=cand.url_anchor,
                dense_rank=cand.dense_rank,
                dense_distance=cand.dense_distance,
                sparse_rank=cand.sparse_rank,
                sparse_score=cand.sparse_score,
                rrf_score=rrf_score,
                rank=fused_rank,
            )
        )
    return hits
