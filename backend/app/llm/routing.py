"""Topic detection and human-contact routing for INV-7 refusals (SDD §5.2 / issue #9).

When confidence is below threshold, the system refuses with the phrase
"I couldn't find this on Laurier's site." and appends the relevant human
contact for the detected topic.  This module owns both detection and the
static S2 routing table.

Topic priority order (first keyword match wins):
  coop → registrar → financial → wellbeing → accessibility → advising (default)

All URLs are public Laurier student-portal pages taken from ingest/seeds.yaml.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HumanContact:
    """A named Laurier office and its public landing URL."""

    topic: str
    office_name: str
    url: str


# ---------------------------------------------------------------------------
# Static routing table (S2 — expand in later sprints as needed)
# ---------------------------------------------------------------------------

_CONTACTS: dict[str, HumanContact] = {
    "coop": HumanContact(
        topic="coop",
        office_name="Career & Experiential Learning (Co-op)",
        url="https://students.wlu.ca/career-and-experiential-learning/co-op/index.html",
    ),
    "registrar": HumanContact(
        topic="registrar",
        office_name="Office of the Registrar",
        url="https://students.wlu.ca/academics/support-and-advising/calendars-and-petitions/petitions-and-appeals/index.html",
    ),
    "financial": HumanContact(
        topic="financial",
        office_name="Financial Aid",
        url="https://students.wlu.ca/finances/financial-aid/index.html",
    ),
    "wellbeing": HumanContact(
        topic="wellbeing",
        office_name="Student Wellness Centre",
        url="https://students.wlu.ca/wellness/index.html",
    ),
    "accessibility": HumanContact(
        topic="accessibility",
        office_name="Accessible Learning Centre",
        url="https://students.wlu.ca/academics/support-and-advising/accessible-learning/index.html",
    ),
    "advising": HumanContact(
        topic="advising",
        office_name="Academic Advising",
        url="https://students.wlu.ca/academics/support-and-advising/academic-advising/index.html",
    ),
}

# Default contact used when no topic keyword matches.
_DEFAULT_TOPIC = "advising"

# ---------------------------------------------------------------------------
# Keyword detection
# Each entry: (topic_key, compiled pattern).  Evaluated in order — first
# match wins.  Patterns are case-insensitive and use word boundaries so that
# e.g. "GPA" does not accidentally match "advising" through a substring.
# ---------------------------------------------------------------------------

_TOPIC_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "coop",
        re.compile(
            r"\b(co[-\s]?op|coop|experiential\s+learning|work\s+term|internship)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "registrar",
        re.compile(
            r"\b(registrar|transcript|enrollment|enrolment|petition|appeal|grade\s+change|official\s+letter)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "financial",
        re.compile(
            r"\b(financial\s+aid|osap|bursary|scholarship|award|tuition|fee|payment)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "wellbeing",
        re.compile(
            r"\b(mental\s+health|counsell?ing|wellness|well[-\s]being|distress|anxiety|depression|support\s+service)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "accessibility",
        re.compile(
            r"\b(accessible?\s+learning|accommodation|alc|disability|assistive)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "advising",
        re.compile(
            r"\b(advis(or|ing|e)|registration|program\s+require|degree\s+require|course\s+select)\b",
            re.IGNORECASE,
        ),
    ),
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_topic(question: str) -> str:
    """Return the topic key for *question*, falling back to the default.

    Iterates ``_TOPIC_PATTERNS`` in priority order; returns the first match.
    An empty or whitespace-only question returns the default topic.
    """
    if not question or not question.strip():
        return _DEFAULT_TOPIC
    for topic_key, pattern in _TOPIC_PATTERNS:
        if pattern.search(question):
            return topic_key
    return _DEFAULT_TOPIC


def contact_for_topic(topic: str) -> HumanContact:
    """Return the HumanContact for *topic*, falling back to the default."""
    return _CONTACTS.get(topic, _CONTACTS[_DEFAULT_TOPIC])
