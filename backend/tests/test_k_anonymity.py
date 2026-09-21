"""INV-6: aggregate reports suppress small counts.

No category is reported below k=5 students; wellbeing categories at the coarsest
useful grain.
"""

import pytest

pytestmark = pytest.mark.skip(reason="Implement alongside the trends report in S4 — SDD §5.5")


def test_small_categories_are_suppressed() -> None: ...
