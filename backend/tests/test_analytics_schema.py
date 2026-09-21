"""INV-3: raw question text is never persisted with identity.

Analytics stores a redacted question, a topic label, and a timestamp — no IP,
no session-to-person linkage, no account.
"""

import pytest

pytestmark = pytest.mark.skip(reason="Implement alongside analytics logging in S4 — SDD §5.5")


def test_analytics_row_has_no_identity_columns() -> None: ...
