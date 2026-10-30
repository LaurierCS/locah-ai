"""Web crawler for public Laurier pages.

Respects robots.txt, enforces the hostname allowlist (INV-1), resolves relative
links against the post-redirect URL, and applies ``CRAWL_MAX_PAGES`` once
across every host.
"""

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Self
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.ingest.seeds import load_seeds
from app.ingest.url_policy import is_crawlable_link, is_error_document_url, is_persistable_fetch

logger = logging.getLogger(__name__)

# Redirects are followed only after the next URL passes the allowlist and
# robots.txt. httpx is not asked to follow them on its own.
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_MAX_REDIRECTS = 5


@dataclass
class CrawlResult:
    """Result of crawling a single URL."""

    url: str
    status: str  # "success", "skip", "error"
    reason: str | None = None  # skip/error reason
    http_status: int | None = None
    content_hash: str | None = None
    body: bytes | None = None
    content_type: str | None = None
    # The URL after all redirects (from httpx response.url). None for skips/errors.
    final_url: str | None = None


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
        # Serializes the global CRAWL_MAX_PAGES reservation. Hosts crawl
        # concurrently; the lock keeps the shared budget from overshooting.
        self._page_lock = asyncio.Lock()

    async def __aenter__(self) -> Self:
        self.http_client = httpx.AsyncClient(
            timeout=30.0,
            headers={"User-Agent": self.config.user_agent},
            follow_redirects=False,
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self.http_client:
            await self.http_client.aclose()

    def normalize_url(self, url: str) -> str | None:
        """Return the canonical crawl URL, or None if it must not be fetched.

        Applied before dedupe:

        - Drop anything that is not http(s) (``mailto:``, ``tel:``,
          ``javascript:``, ``ftp:``, and other schemes stay None — they are
          never rewritten onto https).
        - Force the scheme to https.
        - Lowercase the host. Keep a port only when one was explicit.
        - Drop the fragment.
        - Strip a trailing ``index.html`` path segment so ``/x/`` and
          ``/x/index.html`` are one URL. ``index.php`` is kept (calendar
          pages use it with a query string). A filename that merely ends in
          ``index.html`` (``/my-index.html``) is left alone.
        - Reject hosts that are not on the allowlist (INV-1).
        """
        try:
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https", ""):
                logger.debug(f"Dropping non-http(s) URL: {url}")
                return None

            host_lower = (parsed.hostname or "").lower()

            # Check allowlist (INV-1). Hostname is empty for relative URLs that
            # were not resolved with urljoin first.
            if host_lower not in self.config.allowlist:
                logger.warning(f"URL out-of-scope (host not allowlisted): {url}")
                return None

            netloc = f"{host_lower}:{parsed.port}" if parsed.port else host_lower

            path = parsed.path or "/"
            if path.endswith("/index.html"):
                path = path[: -len("index.html")]

            normalized = f"https://{netloc}{path}"
            if parsed.query:
                normalized += f"?{parsed.query}"
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
            # Leave the parser unparsed. can_fetch() is False until parse()
            # runs, so a failed fetch fails closed (INV-1) instead of
            # treating the host as unrestricted.
        finally:
            self.robots_parsers[host] = parser
        return parser

    async def _robots_allow(self, url: str, host: str) -> bool:
        """Return whether robots.txt for ``host`` allows ``url``.

        ``host`` must be the URL's own hostname. A link discovered on another
        allowlisted host is still judged against the target host's file (INV-1).
        """
        parser = await self.get_robots_txt_parser(host)
        if parser.can_fetch(self.config.user_agent, url):
            return True
        logger.warning(f"Robots.txt disallows: {url}")
        return False

    async def should_crawl_url(self, url: str, host: str) -> bool:
        """Return False when ``url`` was already fetched or robots.txt forbids it.

        Robots.txt is loaded for the URL's hostname. ``host`` is only the
        fallback when the URL has no hostname.
        """
        if url in self.all_fetched:
            logger.debug(f"URL already fetched in session: {url}")
            return False

        url_host = (urlparse(url).hostname or host).lower()
        return await self._robots_allow(url, url_host)

    async def _redirect_target_allowed(self, url: str) -> bool:
        """Return True when a redirect hop may be requested (INV-1).

        Both the hostname allowlist and that host's robots.txt have to allow
        the target. The check is silent; ``crawl_host`` records the skip.
        """
        host = (urlparse(url).hostname or "").lower()
        if host not in self.config.allowlist:
            return False
        parser = await self.get_robots_txt_parser(host)
        return parser.can_fetch(self.config.user_agent, url)

    async def fetch_and_hash(
        self, url: str, etag: str | None = None
    ) -> tuple[bytes, str, int, str | None, str, str]:
        """
        Fetch URL, compute content hash, handle etag.

        Returns (body, content_hash, http_status, new_etag, content_type, final_url).
        Body is empty if unchanged (304), the response was not an accepted
        content type, or the fetch failed.

        Redirects are followed manually, up to ``_MAX_REDIRECTS``. A hop whose
        host is off the allowlist, or which that host's robots.txt disallows,
        is not requested. In that case ``final_url`` is the refused target and
        ``http_status`` is the redirect status, with an empty body.

        ``final_url`` on a completed fetch is the post-redirect URL. Link
        extraction must resolve relative hrefs against it. One retry is
        attempted on a transient RequestError.
        """
        if self.http_client is None:
            raise RuntimeError("HTTP client not initialized")
        client = self.http_client

        async def _do_fetch() -> tuple[bytes, str, int, str | None, str, str]:
            headers: dict[str, str] = {}
            if etag:
                headers["If-None-Match"] = etag

            current = url
            for _hop in range(_MAX_REDIRECTS + 1):
                resp = await client.get(current, headers=headers, follow_redirects=False)
                if resp.status_code == 304:
                    logger.debug(f"304 Not Modified for {current}")
                    return b"", hashlib.sha256(b"").hexdigest(), 304, etag, "", str(resp.url)

                if resp.status_code in _REDIRECT_STATUSES:
                    location = resp.headers.get("location")
                    if not location:
                        return b"", "", resp.status_code, None, "", str(resp.url)
                    next_url = urljoin(str(resp.url), location.strip())
                    if not await self._redirect_target_allowed(next_url):
                        logger.warning(f"Refusing redirect {current} → {next_url}")
                        return b"", "", resp.status_code, None, "", next_url
                    current = next_url
                    headers = {}
                    continue

                final_url = str(resp.url)
                content_type = resp.headers.get("content-type", "").lower()
                if not any(ct in content_type for ct in self.config.content_types):
                    logger.warning(f"Content-type not accepted for {current}: {content_type}")
                    return b"", "", resp.status_code, None, content_type, final_url

                # Hash raw bytes so PDFs and HTML stay consistent with stored etag/hash logic.
                body = resp.content
                content_hash = hashlib.sha256(body).hexdigest()
                new_etag = resp.headers.get("etag")

                logger.debug(
                    f"Fetched {current} — hash {content_hash[:8]}..., status {resp.status_code}"
                )
                return body, content_hash, resp.status_code, new_etag, content_type, final_url

            logger.warning(f"Too many redirects for {url}")
            return b"", "", 0, None, "", current

        try:
            return await _do_fetch()
        except httpx.TimeoutException:
            logger.error(f"Timeout fetching {url}")
            return b"", "", 0, None, "", url
        except httpx.RequestError as e:
            logger.warning(f"Request error for {url}: {e} — retrying once")
            await asyncio.sleep(1.0)
            try:
                return await _do_fetch()
            except (httpx.RequestError, httpx.TimeoutException) as e2:
                logger.error(f"Request error for {url}: {e2}")
                return b"", "", 0, None, "", url

    async def extract_links(
        self, base_url: str, body: bytes, content_type: str, depth: int
    ) -> list[str]:
        """Extract crawlable links from HTML.

        ``base_url`` is the post-redirect final URL. Every navigational href
        is resolved with ``urljoin(base_url, href)`` (absolute hrefs pass
        through urljoin unchanged). Fragment-only hrefs and non-http(s)
        schemes are dropped before resolution so they cannot be rewritten
        onto https.

        A link is returned only after ``normalize_url`` (allowlist plus
        canonical form) and ``is_crawlable_link`` (asset denylist) both pass.
        robots.txt is applied later, before the URL is enqueued or fetched.
        """
        links: list[str] = []
        if not body or depth >= self.config.depth_cap:
            return links
        if "text/html" not in content_type.lower():
            return links

        content = body.decode("utf-8", errors="replace")

        for raw_href in _parse_hrefs(content):
            if not _is_navigational_href(raw_href):
                continue
            resolved = urljoin(base_url, raw_href.strip())
            normalized = self.normalize_url(resolved)
            if not normalized:
                continue
            if not is_crawlable_link(normalized):
                logger.debug(f"Denylist link skipped: {normalized}")
                continue
            if normalized not in links:
                links.append(normalized)
        return links

    def _queue_contains(self, queue: HostQueue, url: str) -> bool:
        return any(url == queued for queued, _depth in queue.urls)

    async def _enqueue(
        self, queue: HostQueue, url: str, depth: int, results: list[CrawlResult]
    ) -> None:
        """Enqueue ``url`` only when allowlist and robots.txt both allow it.

        INV-1: a URL that fails either check never sits on the queue. robots.txt
        is the file for the URL's own host, not the host that discovered it.
        """
        link_host = (urlparse(url).hostname or "").lower()
        if link_host not in self.config.allowlist:
            logger.warning(f"URL out-of-scope (host not allowlisted): {url}")
            return
        if url in self.all_fetched or self._queue_contains(queue, url):
            return
        if not await self._robots_allow(url, link_host):
            results.append(CrawlResult(url, "skip", reason="robots.txt"))
            return
        queue.urls.append((url, depth))

    async def crawl_host(
        self, host: str, seed_urls: list[str], session: AsyncSession | None = None
    ) -> list[CrawlResult]:
        """Crawl one host queue: seeds, then discovered links.

        ``CRAWL_MAX_PAGES`` is a single budget shared with every other host
        (``all_fetched``), not a per-host limit. Seeds that canonicalize to
        the same URL are enqueued once. Discovered links are resolved from
        the post-redirect final URL.
        """
        host_results: list[CrawlResult] = []
        queue = HostQueue(host=host)

        seen_seeds: set[str] = set()
        for seed_url in seed_urls:
            normalized = self.normalize_url(seed_url)
            if not normalized or normalized in seen_seeds:
                continue
            seen_seeds.add(normalized)
            await self._enqueue(queue, normalized, 0, host_results)

        logger.info(f"Starting crawl of {host} with {len(queue.urls)} seeds")

        while queue.urls and len(self.all_fetched) < self.config.max_pages:
            url, depth = queue.urls[0]
            link_host = (urlparse(url).hostname or host).lower()

            if link_host not in self.config.allowlist:
                queue.urls.pop(0)
                host_results.append(CrawlResult(url, "skip", reason="host not allowlisted"))
                continue

            # Enforce per-host concurrency (1) and delay.
            async with queue.semaphore:
                if queue.last_fetch_time:
                    elapsed = (datetime.now(UTC) - queue.last_fetch_time).total_seconds()
                    if elapsed < self.config.delay_seconds:
                        await asyncio.sleep(self.config.delay_seconds - elapsed)

                # robots.txt for this URL's host, and the session dedupe set.
                should_fetch = await self.should_crawl_url(url, link_host)
                if not should_fetch:
                    queue.urls.pop(0)
                    host_results.append(
                        CrawlResult(url, "skip", reason="robots.txt or already fetched")
                    )
                    continue

                # Reserve a slot in the global page budget before the GET so
                # concurrent hosts cannot each pass the cap check.
                async with self._page_lock:
                    if url in self.all_fetched:
                        queue.urls.pop(0)
                        host_results.append(CrawlResult(url, "skip", reason="already fetched"))
                        continue
                    if len(self.all_fetched) >= self.config.max_pages:
                        break
                    self.all_fetched.add(url)
                    queue.fetched.add(url)
                    queue.urls.pop(0)

                (
                    body,
                    content_hash,
                    http_status,
                    _etag,
                    content_type,
                    final_url,
                ) = await self.fetch_and_hash(url)

                queue.last_fetch_time = datetime.now(UTC)
                final_url = final_url or url
                final_host = (urlparse(final_url).hostname or "").lower()

                # A redirect off the allowlist must not be stored or mined
                # for further links (INV-1). The GET already followed the
                # redirect inside httpx; drop the body here.
                if final_host not in self.config.allowlist:
                    logger.warning(f"Redirect left the allowlist for {url} → {final_url}")
                    host_results.append(
                        CrawlResult(
                            url,
                            "skip",
                            reason="redirected off allowlist",
                            final_url=final_url,
                        )
                    )
                    continue

                if not await self._robots_allow(final_url, final_host):
                    host_results.append(
                        CrawlResult(
                            url,
                            "skip",
                            reason="robots.txt disallows redirect target",
                            final_url=final_url,
                        )
                    )
                    continue

                # If the server redirected us to a Laurier error page, treat as
                # a skip so we never persist a junk document row.
                if is_error_document_url(final_url):
                    logger.warning(f"Error page after redirect for {url} → {final_url}")
                    host_results.append(
                        CrawlResult(
                            url, "skip", reason="redirected to error page", final_url=final_url
                        )
                    )
                    continue

                if http_status in (200, 304):
                    host_results.append(
                        CrawlResult(
                            url,
                            "success",
                            http_status=http_status,
                            content_hash=content_hash,
                            body=body if http_status == 200 and body else None,
                            content_type=content_type or None,
                            final_url=final_url,
                        )
                    )
                else:
                    host_results.append(
                        CrawlResult(
                            url,
                            "error",
                            reason=f"HTTP {http_status}",
                            http_status=http_status,
                            final_url=final_url,
                        )
                    )

                # Resolve new links against the post-redirect URL.
                new_links = await self.extract_links(final_url, body, content_type, depth)
                for link in new_links:
                    await self._enqueue(queue, link, depth + 1, host_results)

        logger.info(f"Completed crawl of {host}: {len(queue.fetched)} pages fetched")
        return host_results

    async def crawl_all(self, session: AsyncSession | None = None) -> None:
        """
        Crawl all seed URLs, grouped by host.

        Concurrent across hosts, serial within a host.
        Persists documents to database.
        """
        # Flatten and group seeds by host.
        # load_seeds() reads seeds.yaml and validates hostnames against CRAWL_ALLOWLIST.
        all_seeds: dict[str, list[str]] = {}
        for domain_seeds in load_seeds().values():
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


async def crawl(session: AsyncSession | None = None) -> list[CrawlResult]:
    """
    Main entry point: crawl all seeds and persist to database.

    Returns the full list of CrawlResults so callers (e.g. the orchestrator in
    ``pipeline.run_ingest`` or the admin endpoint #38) can continue processing
    without re-running the crawl.

    Args:
        session: Optional SQLAlchemy async session for persistence.
                 If None, crawler still runs but doesn't persist.

    Returns:
        List of CrawlResult for every URL visited (success, skip, or error).
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

        return crawler.results


async def persist_crawl_results(
    session: AsyncSession,
    results: list[CrawlResult],
    robots_parsers: dict[str, RobotFileParser],
) -> None:
    """Persist successful crawl results to the documents table.

    Only writes rows for fetches that produced real content: status="success"
    with a non-empty body, a valid content_hash, and HTTP 200.  Skipping
    empty-body or non-200 results prevents CSS/304/error-shell rows from
    inflating the documents table without corresponding chunks.
    """
    from sqlalchemy import text

    persisted = 0
    skipped = 0
    for result in results:
        if result.status != "success":
            continue

        # Guard: only persist fetches that produced actual content.
        if not is_persistable_fetch(result.body, result.content_hash, result.http_status):
            logger.info(f"Skipping persist for {result.url} — empty body or non-200 status")
            skipped += 1
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
                    "fetched_at": datetime.now(UTC),
                },
            )
            persisted += 1
        except (ValueError, RuntimeError) as e:
            logger.error(f"Failed to persist {result.url}: {e}")

    await session.commit()
    logger.info(f"Persisted {persisted} documents ({skipped} skipped — empty body/non-200)")


def _is_navigational_href(href: str) -> bool:
    """Return True for http(s) and scheme-less hrefs that ``urljoin`` can resolve.

    Fragment-only links (``#section``) and non-http(s) schemes (``mailto:``,
    ``tel:``, ``javascript:``, ``ftp:``, ``data:``, ...) are not crawl targets.
    """
    stripped = href.strip()
    if not stripped or stripped.startswith("#"):
        return False
    scheme = urlparse(stripped).scheme
    return scheme in ("", "http", "https")


def _parse_hrefs(html: str) -> list[str]:
    """Extract all raw <a href="..."> values from an HTML string."""

    class _LinkExtractor(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.links: list[str] = []

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            if tag == "a":
                for attr, value in attrs:
                    if attr == "href" and value is not None:
                        self.links.append(value)

    parser = _LinkExtractor()
    parser.feed(html)
    return parser.links
