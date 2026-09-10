"""INV-5: distress signals escalate, never de-prioritize.

This is a structural test. It asserts that the safety module exposes no way to
suppress or downrank anything, so a future contributor cannot add one quietly.
"""

import inspect

from app.core import safety

FORBIDDEN = ("suppress", "downrank", "deprioritize", "de_prioritize", "dismiss", "auto_resolve")


def test_no_suppression_api_exists() -> None:
    names = [n.lower() for n, _ in inspect.getmembers(safety)]
    for forbidden in FORBIDDEN:
        assert not any(forbidden in n for n in names), (
            f"INV-5 violated: safety module exposes '{forbidden}'. "
            "The safety gate is one-way — it may only escalate."
        )


def test_outcome_type_cannot_express_suppression() -> None:
    fields = safety.SafetyOutcome.__dataclass_fields__
    assert set(fields) == {"resources", "escalate_to_human"}, (
        "INV-5 violated: SafetyOutcome gained a field. Adding anything beyond "
        "resources and escalation makes suppression representable."
    )
