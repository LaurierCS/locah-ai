"""Unit tests for llm/answer.py (build_refusal) and llm/routing.py — INV-7.

Pure unit tests — no Postgres, no LLM calls.
"""

from __future__ import annotations

from app.llm.answer import _REFUSAL_LEAD_IN, build_refusal
from app.llm.routing import contact_for_topic, detect_topic
from app.retrieval.types import RetrievedChunk

_THRESHOLD = 0.35


# ---------------------------------------------------------------------------
# Helpers (mirrors test_confidence.py factory)
# ---------------------------------------------------------------------------


def _make_chunk(
    rank: int,
    dense_distance: float | None = None,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=f"chunk-{rank}",
        document_id="doc-1",
        ordinal=rank,
        url="https://www.wlu.ca/test",
        title=None,
        text="test",
        heading_path=None,
        url_anchor=None,
        dense_rank=rank if dense_distance is not None else None,
        dense_distance=dense_distance,
        sparse_rank=None,
        sparse_score=None,
        rrf_score=1.0 / (60 + rank),
        rank=rank,
    )


def _strong_chunks() -> list[RetrievedChunk]:
    return [_make_chunk(i + 1, dense_distance=0.05 + i * 0.02) for i in range(8)]


def _weak_chunks() -> list[RetrievedChunk]:
    return [_make_chunk(i + 1, dense_distance=0.75 + i * 0.01) for i in range(8)]


# ---------------------------------------------------------------------------
# build_refusal — success path (should return None)
# ---------------------------------------------------------------------------


def test_high_confidence_returns_none() -> None:
    result = build_refusal("What GPA do I need for co-op?", _strong_chunks(), threshold=_THRESHOLD)
    assert result is None


# ---------------------------------------------------------------------------
# build_refusal — refusal path
# ---------------------------------------------------------------------------


def test_empty_chunks_returns_refusal() -> None:
    result = build_refusal("Some question", [], threshold=_THRESHOLD)
    assert result is not None


def test_low_confidence_returns_refusal() -> None:
    result = build_refusal("Some question", _weak_chunks(), threshold=_THRESHOLD)
    assert result is not None


def test_refusal_message_contains_lead_in() -> None:
    result = build_refusal("Some question", [], threshold=_THRESHOLD)
    assert result is not None
    assert _REFUSAL_LEAD_IN in result.message


def test_refusal_message_contains_office_name() -> None:
    result = build_refusal("Some question", [], threshold=_THRESHOLD)
    assert result is not None
    assert result.contact.office_name in result.message


def test_refusal_message_contains_url() -> None:
    result = build_refusal("Some question", [], threshold=_THRESHOLD)
    assert result is not None
    assert result.contact.url in result.message


def test_refusal_carries_confidence_assessment() -> None:
    result = build_refusal("Some question", _weak_chunks(), threshold=_THRESHOLD)
    assert result is not None
    assert result.confidence.should_refuse is True


# ---------------------------------------------------------------------------
# Topic routing via build_refusal
# ---------------------------------------------------------------------------


def test_coop_question_routes_to_coop() -> None:
    result = build_refusal("What GPA do I need for co-op admission?", [], threshold=_THRESHOLD)
    assert result is not None
    assert result.topic == "coop"
    assert "co-op" in result.contact.office_name.lower()


def test_registrar_question_routes_correctly() -> None:
    result = build_refusal("How do I request an official transcript?", [], threshold=_THRESHOLD)
    assert result is not None
    assert result.topic == "registrar"


def test_financial_question_routes_correctly() -> None:
    result = build_refusal("How do I apply for OSAP?", [], threshold=_THRESHOLD)
    assert result is not None
    assert result.topic == "financial"


def test_generic_question_falls_back_to_advising() -> None:
    result = build_refusal("What time does the library close?", [], threshold=_THRESHOLD)
    assert result is not None
    assert result.topic == "advising"


# ---------------------------------------------------------------------------
# detect_topic — routing table unit tests
# ---------------------------------------------------------------------------


def test_detect_coop_variants() -> None:
    for q in ["co-op deadline", "coop GPA requirement", "work term application"]:
        assert detect_topic(q) == "coop", f"Expected coop for: {q!r}"


def test_detect_registrar_variants() -> None:
    for q in ["How do I file a petition?", "grade change appeal", "transcript request"]:
        assert detect_topic(q) == "registrar", f"Expected registrar for: {q!r}"


def test_detect_financial_variants() -> None:
    for q in ["OSAP renewal", "bursary application", "tuition payment deadline"]:
        assert detect_topic(q) == "financial", f"Expected financial for: {q!r}"


def test_detect_wellbeing_variants() -> None:
    for q in ["mental health resources", "counselling appointment", "wellness programs"]:
        assert detect_topic(q) == "wellbeing", f"Expected wellbeing for: {q!r}"


def test_detect_accessibility_variants() -> None:
    for q in ["accessible learning registration", "ALC accommodation", "disability services"]:
        assert detect_topic(q) == "accessibility", f"Expected accessibility for: {q!r}"


def test_detect_empty_returns_default() -> None:
    assert detect_topic("") == "advising"
    assert detect_topic("   ") == "advising"


def test_detect_unknown_returns_default() -> None:
    assert detect_topic("xyzzy does not match anything") == "advising"


# ---------------------------------------------------------------------------
# contact_for_topic — lookup and fallback
# ---------------------------------------------------------------------------


def test_contact_for_known_topics() -> None:
    for topic in ("coop", "registrar", "financial", "wellbeing", "accessibility", "advising"):
        contact = contact_for_topic(topic)
        assert contact.topic == topic
        assert contact.url.startswith("https://")
        assert contact.office_name


def test_contact_for_unknown_falls_back() -> None:
    contact = contact_for_topic("does_not_exist")
    assert contact.topic == "advising"
