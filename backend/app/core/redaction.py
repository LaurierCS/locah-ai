"""PII redaction — INV-2.

Nothing reaches a model provider except through text that has passed through
`redact()`. The placeholder map lives for the life of one request and is never
written to storage.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
PHONE = re.compile(r"\b(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b")
# Laurier student numbers are 9 digits, commonly written with or without spaces.
STUDENT_NUMBER = re.compile(r"\b\d{9}\b")
POSTAL = re.compile(r"\b[A-Z]\d[A-Z][ -]?\d[A-Z]\d\b", re.IGNORECASE)

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL", EMAIL),
    ("PHONE", PHONE),
    ("STUDENT_NUMBER", STUDENT_NUMBER),
    ("POSTAL", POSTAL),
]


@dataclass
class Redaction:
    """Redacted text plus the map needed to restore it locally."""

    text: str
    placeholders: dict[str, str] = field(default_factory=dict)

    def restore(self, generated: str) -> str:
        """Put the original values back after the model has responded."""
        for token, original in self.placeholders.items():
            generated = generated.replace(token, original)
        return generated


def redact(text: str) -> Redaction:
    """Replace identifying values with stable placeholders.

    Regexes cover structured identifiers (email, phone, student number, postal
    code). A named-entity pass for person names is an S3 deliverable (see #13);
    until then, names may be missed by regex alone.
    """
    placeholders: dict[str, str] = {}
    counters: dict[str, int] = {}

    def make_substituter(label: str) -> Callable[[re.Match[str]], str]:
        """Bind the label explicitly — a closure over the loop variable would
        capture the last label for every pattern."""

        def substitute(match: re.Match[str]) -> str:
            counters[label] = counters.get(label, 0) + 1
            token = f"⟨{label}_{counters[label]}⟩"
            placeholders[token] = match.group(0)
            return token

        return substitute

    for label, pattern in PATTERNS:
        text = pattern.sub(make_substituter(label), text)

    return Redaction(text=text, placeholders=placeholders)
