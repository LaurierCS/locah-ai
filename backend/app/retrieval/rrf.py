"""Reciprocal Rank Fusion (Cormack et al.) — pure, no I/O.

score(d) = Σ_legs 1 / (k + rank_leg(d)) with 1-based ranks.

k=60 is the conventional constant (SDD §5.2 / issue #7). A document that
appears on both legs outranks a single-leg hit at the same best rank.
"""

from __future__ import annotations

from collections.abc import Sequence

DEFAULT_RRF_K = 60


def reciprocal_rank_fusion(
    dense_ids: Sequence[str],
    sparse_ids: Sequence[str],
    *,
    k: int = DEFAULT_RRF_K,
) -> dict[str, float]:
    """Return fused RRF scores keyed by chunk id (union of both ranked lists)."""
    scores: dict[str, float] = {}
    for rank, chunk_id in enumerate(dense_ids, start=1):
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    for rank, chunk_id in enumerate(sparse_ids, start=1):
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return scores


def fused_ranking(scores: dict[str, float]) -> list[tuple[str, float]]:
    """Sort by descending RRF score; tie-break on chunk id for stability."""
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))
