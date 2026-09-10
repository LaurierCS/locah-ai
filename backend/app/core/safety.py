"""Safety gate — INV-5.

A distress signal may only ESCALATE. There is deliberately no function in this
module that suppresses, delays, downranks, or auto-resolves anything, and no PR
should add one. If you find yourself needing one, the design is wrong.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SupportArea(str, Enum):
    WELLBEING = "wellbeing"
    ACCESSIBILITY = "accessibility"
    FINANCIAL = "financial"
    ADVISING = "advising"


@dataclass(frozen=True)
class SupportResource:
    """A support service Laurier already publishes. We surface, we do not advise."""

    area: SupportArea
    name: str
    url: str
    contact: str


@dataclass(frozen=True)
class SafetyOutcome:
    """The only permitted effects: add resources, and route to a human."""

    resources: tuple[SupportResource, ...]
    escalate_to_human: bool


def assess(question: str) -> SafetyOutcome:
    """Detect support-relevant signal and return resources to surface.

    Returns resources to ADD. It never returns a suppression instruction,
    because no such return value exists in this type.

    TODO(retrieval-pod): replace keyword matching with a classifier, keeping
    the same one-way contract.
    """
    raise NotImplementedError("Implement in S3 — see SDD §5.4")
