"""Web crawler for wlu.ca — respects robots.txt, enforces allowlist scope, maintains politeness delays."""

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Self
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

logger = logging.getLogger(__name__)


# TODO(#36): Replace with external seed config loader once issue #36 is complete
# These are placeholder seed URLs for the 8 domain areas from SDD §5.1.
# Issue #36 will implement a proper seeds.yaml loader and test suite.
SEED_URLS: dict[str, list[str]] = {
    "advising": [
        "https://www.wlu.ca/student-advising",
        "https://www.wlu.ca/student-advising/contacts",
    ],
    "academic_calendar": [
        "https://www.wlu.ca/student-services/academic-calendar",
    ],
    "coop": [
        "https://www.wlu.ca/co-op",
    ],
    "important_dates": [
        "https://www.wlu.ca/important-dates",
    ],
    "registrar": [
        "https://www.wlu.ca/registrar",
    ],
    "wellness": [
        "https://www.wlu.ca/student-services/wellness",
    ],
    "accessible_learning": [
        "https://www.wlu.ca/student-services/accessible-learning",
    ],
    "financial_aid": [
        "https://www.wlu.ca/student-services/financial-aid",
    ],
}


@dataclass
class CrawlResult:
    """Result of crawling a single URL."""

    url: str
    status: str  # "success", "skip", "error"
    reason: str | None = None  # skip/error reason
    http_status: int | None = None
    content_hash: str | None = None


@dataclass
class CrawlerConfig:
    """Crawler configuration, wraps settings."""

    allowlist: set[str]
    user_agent: str
    delay_seconds: float
    max_pages: int
    depth_cap: int
    content_types: list[str]


@dataclass
class HostQueue:
    """Per-host crawl queue with rate limiting."""

    host: str
    urls: list[tuple[str, int]] = field(default_factory=list)  # (url, depth)
    fetched: set[str] = field(default_factory=set)
    last_fetch_time: datetime | None = None
    semaphore: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(1))


class CrawlerState:
    """Stateful crawler with robots.txt caching and session management."""

    def __init__(self, config: CrawlerConfig):
        self.config = config
        self.http_client: httpx.AsyncClient | None = None
        self.robots_parsers: dict[str, RobotFileParser] = {}
        self.host_queues: dict[str, HostQueue] = {}
        self.all_fetched: set[str] = set()
        self.results: list[CrawlResult] = []

    async def __aenter__(self) -> Self:
        self.http_client = httpx.AsyncClient(
            timeout=30.0,
            headers={"User-Agent": self.config.user_agent},
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self.http_client:
            await self.http_client.aclose()

    def normalize_url(self, url: str) -> str | None:
        """
        Parse and validate URL against allowlist.

        Returns normalized URL or None if out-of-scope.
        """
        try:
            parsed = urlparse(url)
            host = parsed.hostname or ""
            host_lower = host.lower()

            # Check allowlist (INV-1)
            if host_lower not in self.config.allowlist:
                logger.warning(f"URL out-of-scope (host not allowlisted): {url}")
                return None

            # Reconstruct as normalized URL
            scheme = parsed.scheme or "https"
            netloc = parsed.netloc
            path = parsed.path or "/"
            query = parsed.query
            normalized = f"{scheme}://{netloc}{path}"
            if query:
                normalized += f"?{query}"
            return normalized
        except (ValueError, AttributeError, TypeError) as e:
            logger.warning(f"Failed to parse URL {url}: {e}")
            return None

    async def get_robots_txt_parser(self, host: str) -> RobotFileParser:
        """Fetch and cache robots.txt for a host."""
        if host in self.robots_parsers:
            return self.robots_parsers[host]

        parser = RobotFileParser()
        try:
            robot_url = f"https://{host}/robots.txt"
            if self.http_client is None:
                raise RuntimeError("HTTP client not initialized")
            resp = await self.http_client.get(robot_url)
            parser.parse(resp.text.splitlines())
            logger.debug(f"Fetched robots.txt for {host}")
        except (httpx.RequestError, RuntimeError) as e:
            logger.warning(f"Failed to fetch robots.txt for {host}: {e}")
            # If robots.txt is unavailable, assume no restrictions
        finally:
            self.robots_parsers[host] = parser
        return parser

    async def should_crawl_url(self, url: str, host: str) -> bool:
        """Check if URL should be crawled (robots.txt, already fetched, etc.)."""
        # Already fetched in this session?
        if url in self.all_fetched:
            logger.debug(f"URL already fetched in session: {url}")
            return False

        # Check robots.txt
        parser = await self.get_robots_txt_parser(host)
        if not parser.can_fetch(self.config.user_agent, url):
            logger.warning(f"Robots.txt disallows: {url}")
            return False

        return True

    async def fetch_and_hash(
        self, url: str, etag: str | None = None
    ) -> tuple[str, str, int, str | None]:
        """
        Fetch URL, compute content hash, handle etag.

        Returns (content, content_hash, http_status, new_etag).
        Content is empty if unchanged (304) or fetch failed.
        """
        if self.http_client is None:
            raise RuntimeError("HTTP client not initialized")

        try:
            headers = {}
            if etag:
                headers["If-None-Match"] = etag

            resp = await self.http_client.get(url, headers=headers)

            # 304 Not Modified — content unchanged
            if resp.status_code == 304:
                logger.debug(f"304 Not Modified for {url}")
                return "", hashlib.sha256(b"").hexdigest(), 304, etag

            # Check content-type
            content_type = resp.headers.get("content-type", "").lower()
            if not any(ct in content_type for ct in self.config.content_types):
                logger.warning(f"Content-type not accepted for {url}: {content_type}")
                return "", "", resp.status_code, None

            # Success: compute hash
            content = resp.text
            content_hash = hashlib.sha256(content.encode()).hexdigest()
            new_etag = resp.headers.get("etag")

            logger.debug(f"Fetched {url} — hash {content_hash[:8]}..., status {resp.status_code}")
            return content, content_hash, resp.status_code, new_etag

        except httpx.TimeoutException:
            logger.error(f"Timeout fetching {url}")
            return "", "", 0, None
        except httpx.RequestError as e:
            logger.error(f"Request error for {url}: {e}")
            return "", "", 0, None

    async def extract_links(self, url: str, content: str, depth: int) -> list[str]:
        """Extract internal links from HTML content."""
        links = []
        if not content or depth >= self.config.depth_cap:
            return links

        # Simple regex-based link extraction (trafilatura is for extraction, not link parsing)
        import re

        for match in re.finditer(r'href=["\'](https?://[^\s"\'<>]+)["\']', content):
            link = match.group(1)
            normalized = self.normalize_url(link)
            if normalized:
                links.append(normalized)
        return links

    async def crawl_host(
        self, host: str, seed_urls: list[str], session: AsyncSession | None = None
    ) -> list[CrawlResult]:
        """Crawl a single host: fetch seeds, follow links, respect politeness."""
        host_results: list[CrawlResult] = []
        queue = HostQueue(host=host)

        # Enqueue seeds at depth 0
        for seed_url in seed_urls:
            normalized = self.normalize_url(seed_url)
            if normalized:
                queue.urls.append((normalized, 0))

        logger.info(f"Starting crawl of {host} with {len(queue.urls)} seeds")

        while queue.urls and len(queue.fetched) < self.config.max_pages:
            url, depth = queue.urls.pop(0)

            # Enforce per-host concurrency (1) and delay
            async with queue.semaphore:
                # Rate limiting: ≥1s delay per host
                if queue.last_fetch_time:
                    elapsed = (datetime.now(timezone.utc) - queue.last_fetch_time).total_seconds()
                    if elapsed < self.config.delay_seconds:
                        await asyncio.sleep(self.config.delay_seconds - elapsed)

                # Scope and robots.txt check
                should_fetch = await self.should_crawl_url(url, host)
                if not should_fetch:
                    host_results.append(
                        CrawlResult(url, "skip", reason="robots.txt or already fetched")
                    )
                    continue

                # Fetch and hash
                content, content_hash, http_status, _etag = await self.fetch_and_hash(url)

                queue.last_fetch_time = datetime.now(timezone.utc)
                queue.fetched.add(url)
                self.all_fetched.add(url)

                # Track result
                if http_status in (200, 304):
                    host_results.append(
                        CrawlResult(
                            url,
                            "success",
                            http_status=http_status,
                            content_hash=content_hash,
                        )
                    )
                else:
                    host_results.append(
                        CrawlResult(
                            url,
                            "error",
                            reason=f"HTTP {http_status}",
                            http_status=http_status,
                        )
                    )

                # Extract and enqueue new links
                new_links = await self.extract_links(url, content, depth)
                for link in new_links:
                    if link not in self.all_fetched and link not in [u for u, _ in queue.urls]:
                        queue.urls.append((link, depth + 1))

        logger.info(f"Completed crawl of {host}: {len(queue.fetched)} pages fetched")
        return host_results

    async def crawl_all(self, session: AsyncSession | None = None) -> None:
        """
        Crawl all seed URLs, grouped by host.

        Concurrent across hosts, serial within a host.
        Persists documents to database.
        """
        # Flatten and group seeds by host
        all_seeds: dict[str, list[str]] = {}
        for domain_seeds in SEED_URLS.values():
            for seed_url in domain_seeds:
                parsed = urlparse(seed_url)
                host = parsed.hostname or ""
                if host not in all_seeds:
                    all_seeds[host] = []
                all_seeds[host].append(seed_url)

        logger.info(f"Starting crawl of {len(all_seeds)} hosts")

        # Crawl each host concurrently
        tasks = []
        for host, seeds in all_seeds.items():
            tasks.append(self.crawl_host(host, seeds, session))

        results = await asyncio.gather(*tasks)
        for host_results in results:
            self.results.extend(host_results)

        # Log summary
        success_count = sum(1 for r in self.results if r.status == "success")
        skip_count = sum(1 for r in self.results if r.status == "skip")
        error_count = sum(1 for r in self.results if r.status == "error")
        logger.info(
            f"Crawl complete: {success_count} success, {skip_count} skipped, {error_count} errors"
        )


async def crawl(session: AsyncSession | None = None) -> None:
    """
    Main entry point: crawl all seeds and persist to database.

    Args:
        session: Optional SQLAlchemy async session for persistence.
                 If None, crawler still runs but doesn't persist.
    """
    config = CrawlerConfig(
        allowlist=settings.allowed_hosts,
        user_agent=settings.crawl_user_agent,
        delay_seconds=settings.crawl_delay_seconds,
        max_pages=settings.crawl_max_pages,
        depth_cap=settings.crawl_depth_cap,
        content_types=settings.crawl_content_types_list,
    )

    async with CrawlerState(config) as crawler:
        await crawler.crawl_all(session)

        # Persist results if session available
        if session:
            await persist_crawl_results(session, crawler.results, crawler.robots_parsers)


async def persist_crawl_results(
    session: AsyncSession,
    results: list[CrawlResult],
    robots_parsers: dict[str, RobotFileParser],
) -> None:
    """
    Persist successful crawl results to documents table.

    Only persists successful fetches (status="success").
    Logs errors for inspection.
    """
    from sqlalchemy import text

    for result in results:
        if result.status != "success":
            continue

        try:
            # Insert or update document
            # Use ON CONFLICT to handle re-crawls of existing URLs
            await session.execute(
                text(
                    """
                    INSERT INTO documents (url, content_hash, http_status, fetched_at)
                    VALUES (:url, :content_hash, :http_status, :fetched_at)
                    ON CONFLICT (url) DO UPDATE SET
                        content_hash = EXCLUDED.content_hash,
                        http_status = EXCLUDED.http_status,
                        fetched_at = EXCLUDED.fetched_at
                    """
                ),
                {
                    "url": result.url,
                    "content_hash": result.content_hash,
                    "http_status": result.http_status,
                    "fetched_at": datetime.now(timezone.utc),
                },
            )
        except (ValueError, RuntimeError) as e:
            logger.error(f"Failed to persist {result.url}: {e}")

    await session.commit()
    logger.info(f"Persisted {sum(1 for r in results if r.status == 'success')} documents")
