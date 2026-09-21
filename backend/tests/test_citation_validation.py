"""INV-4: every factual sentence carries a citation.

Every citation must resolve to a URL actually present in the retrieved context;
the post-generation validator rejects unsupported claims.
"""

import pytest

pytestmark = pytest.mark.skip(reason="Implement alongside the citation validator in S3 — SDD §5.3")


def test_uncited_claim_is_rejected() -> None: ...
