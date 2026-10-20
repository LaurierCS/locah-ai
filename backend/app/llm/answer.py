"""Answer synthesis and refusal — Retrieval pod (SDD §5.3 / issue #71, #9).

S2 scope: refusal path only (INV-7).
  - build_refusal  →  returns a RefusalResult when confidence is too low.
  - Synthesis (generate_answer) lands with #71.

Refusal message format (INV-7):
  "I couldn't find this on Laurier's site. For help with <topic>, please
   contact <office_name>: <url>"
"""

from __future__ import annotations

from dataclasses import dataclass

from app.llm.routing import HumanContact, contact_for_topic, detect_topic
from app.retrieval.confidence import ConfidenceAssessment, assess_confidence
from app.retrieval.types import RetrievedChunk

# Exact lead-in required by INV-7 / SDD §5.2 issue description.
_REFUSAL_LEAD_IN = "I couldn't find this on Laurier's site."


@dataclass(frozen=True)
class RefusalResult:
    """Everything needed to render an INV-7 refusal response."""

    message: str
    topic: str
    contact: HumanContact
    confidence: ConfidenceAssessment


def _format_refusal_message(contact: HumanContact) -> str:
    return (
        f"{_REFUSAL_LEAD_IN} For help with this topic, please contact "
        f"{contact.office_name}: {contact.url}"
    )


def build_refusal(
    question: str,
    chunks: list[RetrievedChunk],
    *,
    threshold: float | None = None,
) -> RefusalResult | None:
    """Assess confidence and build a refusal if the threshold is not met.

    Returns:
        A ``RefusalResult`` when the system should refuse, ``None`` when the
        retrieval is strong enough to proceed to synthesis (#71).

    The caller (#72 ask pipeline) should treat a non-None return as the
    terminal answer — do not call the LLM when refused.
    """
    assessment = assess_confidence(chunks, threshold=threshold)
    if not assessment.should_refuse:
        return None

    topic = detect_topic(question)
    contact = contact_for_topic(topic)
    message = _format_refusal_message(contact)

    return RefusalResult(
        message=message,
        topic=topic,
        contact=contact,
        confidence=assessment,
    )
