"""Retrieved-chunk contract for hybrid search (SDD §5.2 / issue #7).

Per-leg ranks and scores are optional because a chunk can appear on only one
leg. Downstream confidence (#9) should use dense_distance without re-querying.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RetrievedChunk:
    """One fused hit after dense + sparse RRF, trimmed to retrieval_top_k."""

    chunk_id: str
    document_id: str
    ordinal: int
    url: str
    title: str | None
    text: str
    heading_path: str | None
    url_anchor: str | None
    # 1-based ranks within each candidate list; None if the chunk missed that leg.
    dense_rank: int | None
    dense_distance: float | None
    sparse_rank: int | None
    sparse_score: float | None
    rrf_score: float
    rank: int  # 1-based fused rank after trim
