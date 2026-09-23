"""INV-1: the knowledge base holds public wlu.ca pages only."""

from unittest.mock import MagicMock

import pytest

from app.core.config import settings
from app.ingest.crawler import CrawlerConfig, CrawlerState


def test_allowlist_is_configured() -> None:
    assert "wlu.ca" in settings.allowed_hosts
    assert "legacy.wlu.ca" in settings.allowed_hosts


def test_offsite_url_is_rejected() -> None:
    """Offsite URLs (not in allowlist) are rejected by normalize_url."""
    config = CrawlerConfig(
        allowlist=settings.allowed_hosts,
        user_agent=settings.crawl_user_agent,
        delay_seconds=settings.crawl_delay_seconds,
        max_pages=settings.crawl_max_pages,
        depth_cap=2,
        content_types=["text/html", "application/pdf"],
    )
    crawler = CrawlerState(config)

    # Offsite URL should be rejected
    result = crawler.normalize_url("https://example.com/page")
    assert result is None, "Offsite URL should not be normalized"

    # On-allowlist URL should be accepted
    result = crawler.normalize_url("https://www.wlu.ca/page")
    assert result == "https://www.wlu.ca/page"

    # Another allowlisted host
    result = crawler.normalize_url("https://legacy.wlu.ca/old-page")
    assert result == "https://legacy.wlu.ca/old-page"


@pytest.mark.asyncio
async def test_robots_disallow_is_respected() -> None:
    """URLs disallowed by robots.txt are skipped."""
    config = CrawlerConfig(
        allowlist=settings.allowed_hosts,
        user_agent=settings.crawl_user_agent,
        delay_seconds=settings.crawl_delay_seconds,
        max_pages=settings.crawl_max_pages,
        depth_cap=2,
        content_types=["text/html", "application/pdf"],
    )
    crawler = CrawlerState(config)

    # Mock robots.txt parser
    mock_parser = MagicMock()
    mock_parser.can_fetch.return_value = False  # Disallow everything

    # Manually set the cached parser to avoid HTTP request
    crawler.robots_parsers["www.wlu.ca"] = mock_parser

    # URL should be skipped because robots.txt disallows it
    should_crawl = await crawler.should_crawl_url("https://www.wlu.ca/admin", "www.wlu.ca")
    assert not should_crawl, "URL disallowed by robots.txt should not be crawled"

    # Verify can_fetch was called with correct params
    mock_parser.can_fetch.assert_called()

    # Now test with robots.txt that allows
    mock_parser.can_fetch.return_value = True
    should_crawl = await crawler.should_crawl_url("https://www.wlu.ca/public", "www.wlu.ca")
    assert should_crawl, "URL allowed by robots.txt should be crawled"
