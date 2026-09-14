"""INV-1: the knowledge base holds public wlu.ca pages only."""

import pytest

from app.core.config import settings

pytestmark = pytest.mark.skip(reason="Implement alongside the crawler in S1 — SDD §5.1")


def test_offsite_url_is_rejected() -> None: ...


def test_robots_disallow_is_respected() -> None: ...


def test_allowlist_is_configured() -> None:
    assert "wlu.ca" in settings.allowed_hosts
    assert "legacy.wlu.ca" in settings.allowed_hosts
