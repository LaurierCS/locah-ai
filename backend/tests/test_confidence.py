"""Unit tests for retrieval/confidence.py — INV-7 (SDD §5.2 / issue #9).

Pure computation — no Postgres, no network.  Chunks are built from a small
factory that sets only the fields confidence.py cares about.
"""

from __future__ import annotations

import pytest

from app.retrieval.confidence import (
    _W_GAP,
    _W_SUPPORT,
    _W_TOP1,
    ConfidenceBreakdown,
    assess_confidence,
)
from app.retrieval.types import RetrievedChunk

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

_THRESHOLD = 0.35  # mirrors settings default; passed explicitly so tests are
#                    independent of the live config value


def _make_chunk(
    rank: int,
    dense_distance: float | None = None,
    sparse_score: float | None = None,
) -> RetrievedChunk:
    """Build a minimal RetrievedChunk with controllable dense_distance."""
    return RetrievedChunk(
        chunk_id=f"chunk-{rank}",
        document_id="doc-1",
        ordinal=rank,
        url="https://www.wlu.ca/test",
        title=None,
        text="test text",
        heading_path=None,
        url_anchor=None,
        dense_rank=rank if dense_distance is not None else None,
        dense_distance=dense_distance,
        sparse_rank=rank if sparse_score is not None else None,
        sparse_score=sparse_score,
        rrf_score=1.0 / (60 + rank),
        rank=rank,
    )


def _strong_chunks(n: int = 8) -> list[RetrievedChunk]:
    """Return n chunks with strong dense distances (high similarity)."""
    # dense_distance ≈ 0.05 → similarity ≈ 0.95
    return [_make_chunk(i + 1, dense_distance=0.05 + i * 0.02) for i in range(n)]


def _weak_chunks(n: int = 8) -> list[RetrievedChunk]:
    """Return n chunks with weak dense distances (low similarity)."""
    # dense_distance ≈ 0.75 → similarity ≈ 0.25 (below 0.35 threshold)
    return [_make_chunk(i + 1, dense_distance=0.75 + i * 0.01) for i in range(n)]


# ---------------------------------------------------------------------------
# Empty list
# ---------------------------------------------------------------------------


def test_empty_chunks_refuse() -> None:
    result = assess_confidence([], threshold=_THRESHOLD)
    assert result.should_refuse is True
    assert result.breakdown.score == 0.0
    assert result.breakdown.top1_similarity == 0.0
    assert result.breakdown.chunks_above_threshold == 0


# ---------------------------------------------------------------------------
# Strong retrieval — should not refuse
# ---------------------------------------------------------------------------


def test_strong_chunks_not_refused() -> None:
    result = assess_confidence(_strong_chunks(), threshold=_THRESHOLD)
    assert result.should_refuse is False
    assert result.breakdown.score >= _THRESHOLD
    assert result.breakdown.top1_similarity > 0.9
    assert result.breakdown.chunks_above_threshold > 0


def test_strong_chunks_breakdown_fields() -> None:
    chunks = _strong_chunks()
    bd = assess_confidence(chunks, threshold=_THRESHOLD).breakdown
    assert isinstance(bd, ConfidenceBreakdown)
    assert 0.0 <= bd.score <= 1.0
    assert bd.top1_top5_gap >= 0.0


# ---------------------------------------------------------------------------
# Weak retrieval — should refuse
# ---------------------------------------------------------------------------


def test_weak_chunks_refused() -> None:
    result = assess_confidence(_weak_chunks(), threshold=_THRESHOLD)
    assert result.should_refuse is True
    assert result.breakdown.score < _THRESHOLD


def test_weak_top1_refused() -> None:
    # Single chunk with similarity well below threshold.
    result = assess_confidence(
        [_make_chunk(1, dense_distance=0.80)],
        threshold=_THRESHOLD,
    )
    assert result.should_refuse is True


# ---------------------------------------------------------------------------
# Sparse-only hit (no dense leg)
# ---------------------------------------------------------------------------


def test_sparse_only_hits_refused() -> None:
    # All chunks lack dense_distance — similarity treated as 0.
    sparse_chunks = [_make_chunk(i + 1, sparse_score=1.0) for i in range(5)]
    result = assess_confidence(sparse_chunks, threshold=_THRESHOLD)
    assert result.should_refuse is True
    assert result.breakdown.top1_similarity == 0.0


# ---------------------------------------------------------------------------
# Fewer than 5 chunks — gap uses rank min(5, n)
# ---------------------------------------------------------------------------


def test_gap_with_two_chunks() -> None:
    """With only 2 chunks, gap is computed between rank-1 and rank-2."""
    chunks = [
        _make_chunk(1, dense_distance=0.05),  # sim ≈ 0.95
        _make_chunk(2, dense_distance=0.50),  # sim ≈ 0.50
    ]
    bd = assess_confidence(chunks, threshold=_THRESHOLD).breakdown
    expected_gap = (1.0 - 0.05) - (1.0 - 0.50)
    assert abs(bd.top1_top5_gap - expected_gap) < 1e-6


def test_gap_with_single_chunk() -> None:
    """With a single chunk, top-1 and rank-min(5,1) are the same → gap = 0."""
    chunks = [_make_chunk(1, dense_distance=0.05)]
    bd = assess_confidence(chunks, threshold=_THRESHOLD).breakdown
    assert bd.top1_top5_gap == 0.0


# ---------------------------------------------------------------------------
# Threshold customisation
# ---------------------------------------------------------------------------


def test_custom_threshold_high() -> None:
    # Strong chunks but threshold raised to 1.0 — must refuse.
    result = assess_confidence(_strong_chunks(), threshold=1.0)
    assert result.should_refuse is True


def test_custom_threshold_zero() -> None:
    # Threshold of 0 — empty list still refuses, non-empty should not.
    result = assess_confidence(_weak_chunks(), threshold=0.0)
    assert result.should_refuse is False


# ---------------------------------------------------------------------------
# Score is deterministic and within bounds
# ---------------------------------------------------------------------------


def test_score_is_bounded() -> None:
    for chunks in [[], _strong_chunks(), _weak_chunks()]:
        bd = assess_confidence(chunks, threshold=_THRESHOLD).breakdown
        assert 0.0 <= bd.score <= 1.0


def test_score_weights_sum_to_one() -> None:
    """Sanity check that the weight constants add up (guards against drift)."""
    assert abs(_W_TOP1 + _W_GAP + _W_SUPPORT - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# ConfidenceAssessment is a frozen dataclass
# ---------------------------------------------------------------------------


def test_assessment_is_immutable() -> None:
    result = assess_confidence([], threshold=_THRESHOLD)
    with pytest.raises((AttributeError, TypeError)):
        result.should_refuse = False  # type: ignore[misc]
