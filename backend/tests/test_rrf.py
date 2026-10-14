"""Unit tests for reciprocal rank fusion (issue #7). No database."""

from app.retrieval.rrf import fused_ranking, reciprocal_rank_fusion


def test_rrf_matches_hand_calculation() -> None:
    # dense: a, b   sparse: b, c   k=60
    # a: 1/61
    # b: 1/62 + 1/61
    # c: 1/62
    scores = reciprocal_rank_fusion(["a", "b"], ["b", "c"], k=60)
    assert scores["a"] == 1.0 / 61
    assert scores["b"] == 1.0 / 62 + 1.0 / 61
    assert scores["c"] == 1.0 / 62


def test_chunk_on_both_legs_outranks_single_leg() -> None:
    scores = reciprocal_rank_fusion(["only_dense", "both"], ["both"], k=60)
    assert scores["both"] > scores["only_dense"]
    ranking = fused_ranking(scores)
    assert ranking[0][0] == "both"


def test_tie_breaks_on_chunk_id() -> None:
    # Identical single-leg rank-1 scores; id order is the tie-break.
    scores = reciprocal_rank_fusion(["z-id"], ["a-id"], k=60)
    assert scores["z-id"] == scores["a-id"]
    ranking = fused_ranking(scores)
    assert [cid for cid, _ in ranking] == ["a-id", "z-id"]
