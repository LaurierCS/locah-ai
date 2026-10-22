"""Retrieval confidence scoring — INV-7 (SDD §5.2 / issue #9).

Produces a scalar confidence score in [0, 1] from the fused chunk list returned
by hybrid_search, then decides whether to refuse.  The caller (llm/answer.py)
issues the refusal message; this module is pure computation, no I/O.

Scoring formula
---------------
Three signals are combined with fixed weights:

  signal          definition                                    weight
  ─────────────   ────────────────────────────────────────────  ──────
  top1            dense_similarity(chunks[0])                    0.55
  gap             normalised gap between top-1 and rank-5 sims   0.25
  support         fraction of chunks with sim ≥ threshold        0.20

``dense_similarity`` converts pgvector cosine *distance* (0 = identical,
2 = opposite) to a similarity in [0, 1]:  ``sim = max(0, 1 - distance)``.
Embeddings are L2-normalised (ADR-006), so cosine distance is already in [0, 2]
and similarity equals the standard cosine similarity for unit vectors.

Gap normalisation: gap / 0.15, capped at 1.0.  A gap of ≥ 0.15 between the
best and fifth-best result signals a clear winner; anything less is murky.

Support normalisation: min(count / 3, 1.0).  Three or more chunks above the
threshold is considered full support.

Refusal rule: ``score < threshold`` OR ``chunks`` is empty.

Public API
----------
``assess_confidence(chunks, *, threshold=None) -> ConfidenceAssessment``
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import settings
from app.retrieval.types import RetrievedChunk

# Weights must sum to 1.0.
_W_TOP1 = 0.55
_W_GAP = 0.25
_W_SUPPORT = 0.20

# Gap of ≥ this value between top-1 and rank-5 similarity scores full marks.
_GAP_NORM = 0.15

# Support reaches full marks at this many chunks above threshold.
_SUPPORT_FULL_AT = 3


@dataclass(frozen=True)
class ConfidenceBreakdown:
    """Per-signal contributions, exposed for logging and the eval harness."""

    top1_similarity: float  # dense similarity of the best chunk
    top1_top5_gap: float  # raw gap (top-1 sim − rank-5 sim)
    chunks_above_threshold: int
    score: float  # weighted composite in [0, 1]


@dataclass(frozen=True)
class ConfidenceAssessment:
    breakdown: ConfidenceBreakdown
    should_refuse: bool


def _dense_sim(chunk: RetrievedChunk) -> float:
    """Convert pgvector cosine distance to similarity in [0, 1].

    Returns 0.0 when the dense leg did not score this chunk (sparse-only hit).
    """
    if chunk.dense_distance is None:
        return 0.0
    return max(0.0, 1.0 - chunk.dense_distance)


def _compute_score(
    chunks: list[RetrievedChunk],
    threshold: float,
) -> ConfidenceBreakdown:
    if not chunks:
        return ConfidenceBreakdown(
            top1_similarity=0.0,
            top1_top5_gap=0.0,
            chunks_above_threshold=0,
            score=0.0,
        )

    top1_sim = _dense_sim(chunks[0])

    # Use rank min(5, n) − 1 (0-indexed) as the "rank-5" reference.
    rank5_idx = min(5, len(chunks)) - 1
    rank5_sim = _dense_sim(chunks[rank5_idx])
    gap = top1_sim - rank5_sim  # always ≥ 0 since list is rank-ordered

    above = sum(1 for c in chunks if _dense_sim(c) >= threshold)

    # Normalise each signal to [0, 1] before weighting.
    norm_top1 = top1_sim
    norm_gap = min(gap / _GAP_NORM, 1.0)
    norm_support = min(above / _SUPPORT_FULL_AT, 1.0)

    score = _W_TOP1 * norm_top1 + _W_GAP * norm_gap + _W_SUPPORT * norm_support

    return ConfidenceBreakdown(
        top1_similarity=top1_sim,
        top1_top5_gap=gap,
        chunks_above_threshold=above,
        score=round(score, 6),
    )


def assess_confidence(
    chunks: list[RetrievedChunk],
    *,
    threshold: float | None = None,
) -> ConfidenceAssessment:
    """Score retrieval confidence and decide whether to refuse.

    Args:
        chunks:    Fused, rank-ordered list from hybrid_search.
        threshold: Override settings.confidence_threshold (for tests).

    Returns:
        A ConfidenceAssessment whose ``should_refuse`` is True when the score
        falls below the threshold or the chunk list is empty.
    """
    t = threshold if threshold is not None else settings.confidence_threshold
    breakdown = _compute_score(chunks, t)
    should_refuse = (not chunks) or (breakdown.score < t)
    return ConfidenceAssessment(breakdown=breakdown, should_refuse=should_refuse)
