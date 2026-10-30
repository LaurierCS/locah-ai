"""INV-1: the knowledge base holds public wlu.ca pages only.

Crawl tests that open an HTTP client use respx plus reserved ``.test`` hosts.
They must not contact wlu.ca (issue #1 ICT signoff is unresolved).
"""

import asyncio
from unittest.mock import MagicMock
from urllib.robotparser import RobotFileParser

import httpx
import pytest
import respx

from app.core.config import settings
from app.ingest.crawler import CrawlerConfig, CrawlerState

_HTML = {"content-type": "text/html"}


def test_allowlist_is_configured() -> None:
    assert "wlu.ca" in settings.allowed_hosts
    assert "legacy.wlu.ca" in settings.allowed_hosts
    assert "students.wlu.ca" in settings.allowed_hosts
    assert "academic-calendar.wlu.ca" in settings.allowed_hosts


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

    # Academic calendar host must be accepted
    result = crawler.normalize_url("https://academic-calendar.wlu.ca/section.php?cal=1&s=1156&y=92")
    assert result is not None


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


def _state(
    *,
    allowlist: set[str] | None = None,
    max_pages: int = 20,
    depth_cap: int = 2,
    delay_seconds: float = 0,
) -> CrawlerState:
    config = CrawlerConfig(
        allowlist=allowlist if allowlist is not None else settings.allowed_hosts,
        user_agent=settings.crawl_user_agent,
        delay_seconds=delay_seconds,
        max_pages=max_pages,
        depth_cap=depth_cap,
        content_types=["text/html", "application/pdf"],
    )
    return CrawlerState(config)


def _allow_all_robots(crawler: CrawlerState, *hosts: str) -> None:
    parser = RobotFileParser()
    parser.parse(["User-agent: *", "Allow: /"])
    for host in hosts:
        crawler.robots_parsers[host] = parser


def test_normalize_url_canonicalizes_before_dedupe() -> None:
    crawler = _state()
    directory = "https://students.wlu.ca/academics/support-and-advising/academic-advising/"
    with_index = (
        "http://Students.WLU.ca/academics/support-and-advising/academic-advising/index.html#hours"
    )
    assert crawler.normalize_url(directory) == directory
    assert crawler.normalize_url(with_index) == directory

    assert crawler.normalize_url("https://WWW.WLU.ca:8443/foo/index.html#x") == (
        "https://www.wlu.ca:8443/foo/"
    )
    # Only a whole trailing index.html segment is removed.
    assert (
        crawler.normalize_url("https://www.wlu.ca/foo/my-index.html")
        == "https://www.wlu.ca/foo/my-index.html"
    )
    assert crawler.normalize_url("https://www.wlu.ca/page#section") == "https://www.wlu.ca/page"
    # Calendar pages keep index.php and the query string.
    calendar = "https://academic-calendar.wlu.ca/index.php?cal=1&y=92"
    assert crawler.normalize_url(calendar) == calendar

    assert crawler.normalize_url("mailto:advisor@wlu.ca") is None
    assert crawler.normalize_url("tel:+15555550123") is None
    assert crawler.normalize_url("javascript:alert(1)") is None
    assert crawler.normalize_url("ftp://www.wlu.ca/files/a") is None
    assert crawler.normalize_url("https://example.com/page") is None


@pytest.mark.asyncio
async def test_extract_links_from_html_file() -> None:
    """Relative, root-relative, and absolute hrefs are canonicalized together."""
    crawler = _state()
    base = "https://students.wlu.ca/academics/support-and-advising/academic-advising/"
    html = b"""
    <html><body>
      <a href="http://students.wlu.ca/academics/index.html">Valid</a>
      <a href="https://students.wlu.ca/academics/">Valid too</a>
      <a href="https://students.wlu.ca/academics/index.html#section1">With Fragment</a>
      <a href="https://example.com/offsite">Offsite</a>
      <a href="https://www.wlu.ca/assets/app.css">CSS Asset</a>
      <a href="/relative/index.html">Root relative</a>
      <a href="subpage.html">Document relative</a>
      <a href="../page.html">Parent relative</a>
      <a href="https://Students.WLU.ca/Foo/my-index.html">Mixed case host</a>
      <a href="section.php?cal=1&amp;y=92">Query relative</a>
      <a href="mailto:advisor@wlu.ca">Mail</a>
      <a href="tel:+15555550123">Phone</a>
      <a href="javascript:void(0)">Script</a>
      <a href="ftp://students.wlu.ca/files/a">Ftp</a>
      <a href="#section">Fragment only</a>
    </body></html>
    """

    links = await crawler.extract_links(base, html, "text/html", depth=0)
    assert links == [
        "https://students.wlu.ca/academics/",
        "https://students.wlu.ca/relative/",
        "https://students.wlu.ca/academics/support-and-advising/academic-advising/subpage.html",
        "https://students.wlu.ca/academics/support-and-advising/page.html",
        "https://students.wlu.ca/Foo/my-index.html",
        "https://students.wlu.ca/academics/support-and-advising/academic-advising/section.php?cal=1&y=92",
    ]
    assert all("#" not in link for link in links)
    assert all(not link.startswith("ftp:") for link in links)
    assert all("mailto" not in link for link in links)


@pytest.mark.asyncio
async def test_extract_links_keeps_calendar_query_urls() -> None:
    crawler = _state()
    base = "https://academic-calendar.wlu.ca/index.php?cal=1"
    html = b'<a href="section.php?cal=1&y=92">Section</a><a href="index.php?cal=1&y=92">Index</a>'
    links = await crawler.extract_links(base, html, "text/html", depth=0)
    assert links == [
        "https://academic-calendar.wlu.ca/section.php?cal=1&y=92",
        "https://academic-calendar.wlu.ca/index.php?cal=1&y=92",
    ]


@pytest.mark.asyncio
async def test_duplicate_index_html_seeds_are_fetched_once() -> None:
    host = "students.test"
    canonical = "https://students.test/academics/support-and-advising/academic-advising/"
    crawler = _state(allowlist={host}, max_pages=10)
    _allow_all_robots(crawler, host)
    seeds = [
        canonical,
        canonical + "index.html",
        "http://Students.Test/academics/support-and-advising/academic-advising/index.html#top",
    ]

    async with crawler:
        with respx.mock:
            route = respx.get(canonical).mock(
                return_value=httpx.Response(200, content=b"<html></html>", headers=_HTML)
            )
            results = await crawler.crawl_host(host, seeds)

    assert route.call_count == 1
    assert [result.status for result in results] == ["success"]


@pytest.mark.asyncio
async def test_relative_links_are_followed_during_crawl() -> None:
    """A fixture page with only relative hrefs contributes more than the seed.

    Those hrefs used to be dropped, so this crawl reached 1 page. Resolving
    them against the final URL reaches the seed plus each in-scope target.
    """
    host = "students.test"
    seed = "https://students.test/academics/"
    support = "https://students.test/academics/support.html"
    advising = "https://students.test/academics/advising/"
    wellness = "https://students.test/wellness.html"
    crawler = _state(allowlist={host}, max_pages=10, depth_cap=2)
    _allow_all_robots(crawler, host)
    html = b"""
    <html><body>
      <a href="support.html">Support</a>
      <a href="advising/index.html">Advising</a>
      <a href="../wellness.html">Wellness</a>
      <a href="mailto:advisor@wlu.ca">Mail</a>
      <a href="https://example.test/offsite">Offsite</a>
    </body></html>
    """

    async with crawler:
        with respx.mock:
            respx.get(seed).mock(return_value=httpx.Response(200, content=html, headers=_HTML))
            respx.get(support).mock(
                return_value=httpx.Response(200, content=b"<html></html>", headers=_HTML)
            )
            respx.get(advising).mock(
                return_value=httpx.Response(200, content=b"<html></html>", headers=_HTML)
            )
            respx.get(wellness).mock(
                return_value=httpx.Response(200, content=b"<html></html>", headers=_HTML)
            )
            results = await crawler.crawl_host(host, [seed])

    fetched = {result.url for result in results if result.status == "success"}
    assert fetched == {seed, support, advising, wellness}
    assert len(fetched) == 4


@pytest.mark.asyncio
async def test_relative_links_resolve_against_post_redirect_final_url() -> None:
    host = "students.test"
    seed = "https://students.test/dir"
    final = "https://students.test/dir/"
    child = "https://students.test/dir/subpage.html"
    crawler = _state(allowlist={host}, max_pages=10, depth_cap=2)
    _allow_all_robots(crawler, host)

    async with crawler:
        with respx.mock:
            respx.get(seed).mock(return_value=httpx.Response(302, headers={"location": final}))
            respx.get(final).mock(
                return_value=httpx.Response(
                    200,
                    content=b'<html><a href="subpage.html">Sub</a></html>',
                    headers=_HTML,
                )
            )
            child_route = respx.get(child).mock(
                return_value=httpx.Response(200, content=b"<html></html>", headers=_HTML)
            )
            await crawler.crawl_host(host, [seed])

    assert child_route.call_count == 1
    assert child in crawler.all_fetched


@pytest.mark.asyncio
async def test_off_allowlist_redirect_is_not_fetched_or_mined() -> None:
    host = "students.test"
    seed = "https://students.test/go"
    offsite = "https://offsite.test/landed"
    crawler = _state(allowlist={host}, max_pages=10, depth_cap=2)
    _allow_all_robots(crawler, host)
    offsite_html = b"""
    <html>
      <a href="https://students.test/from-offsite.html">Back</a>
      <a href="rel.html">Rel</a>
    </html>
    """

    async with crawler:
        with respx.mock:
            respx.get(seed).mock(return_value=httpx.Response(302, headers={"location": offsite}))
            offsite_route = respx.get(offsite).mock(
                return_value=httpx.Response(200, content=offsite_html, headers=_HTML)
            )
            follow = respx.get("https://students.test/from-offsite.html").mock(
                return_value=httpx.Response(200, content=b"<html></html>", headers=_HTML)
            )
            relative = respx.get("https://offsite.test/rel.html").mock(
                return_value=httpx.Response(200, content=b"<html></html>", headers=_HTML)
            )
            results = await crawler.crawl_host(host, [seed])

    assert offsite_route.call_count == 0
    assert follow.call_count == 0
    assert relative.call_count == 0
    assert results[0].status == "skip"
    assert results[0].reason == "redirected off allowlist"
    assert "https://students.test/from-offsite.html" not in crawler.all_fetched


@pytest.mark.asyncio
async def test_robots_disallow_on_redirect_target_is_not_fetched() -> None:
    host = "students.test"
    crawler = _state(allowlist={host}, max_pages=10, depth_cap=2)
    parser = RobotFileParser()
    parser.parse(["User-agent: *", "Disallow: /secret"])
    crawler.robots_parsers[host] = parser

    async with crawler:
        with respx.mock:
            respx.get("https://students.test/public").mock(
                return_value=httpx.Response(
                    302, headers={"location": "https://students.test/secret"}
                )
            )
            secret = respx.get("https://students.test/secret").mock(
                return_value=httpx.Response(
                    200,
                    content=b'<a href="/more.html">More</a>',
                    headers=_HTML,
                )
            )
            more = respx.get("https://students.test/more.html").mock(
                return_value=httpx.Response(200, content=b"<html></html>", headers=_HTML)
            )
            results = await crawler.crawl_host(host, ["https://students.test/public"])

    assert secret.call_count == 0
    assert more.call_count == 0
    assert results[0].status == "skip"
    assert results[0].reason == "robots.txt disallows redirect target"


@pytest.mark.asyncio
async def test_robots_txt_of_the_link_host_gates_enqueue() -> None:
    """A link to another allowlisted host uses that host's robots.txt."""
    source = "students.test"
    target = "www.test"
    crawler = _state(allowlist={source, target}, max_pages=10, depth_cap=2)
    _allow_all_robots(crawler, source)
    seed = "https://students.test/home.html"
    html = b"""
    <html>
      <a href="https://www.test/secret">Secret</a>
      <a href="https://www.test/public.html">Public</a>
    </html>
    """

    async with crawler:
        with respx.mock:
            respx.get(seed).mock(return_value=httpx.Response(200, content=html, headers=_HTML))
            respx.get("https://www.test/robots.txt").mock(
                return_value=httpx.Response(
                    200, text="User-agent: *\nDisallow: /secret\nAllow: /\n"
                )
            )
            secret = respx.get("https://www.test/secret").mock(
                return_value=httpx.Response(200, content=b"<html>no</html>", headers=_HTML)
            )
            public = respx.get("https://www.test/public.html").mock(
                return_value=httpx.Response(200, content=b"<html></html>", headers=_HTML)
            )
            await crawler.crawl_host(source, [seed])

    assert secret.call_count == 0
    assert public.call_count == 1


@pytest.mark.asyncio
async def test_max_pages_cap_is_shared_across_hosts() -> None:
    """Three pages total, not three per host. Each host advertises many links."""
    hosts = ("alpha.test", "beta.test")
    crawler = _state(allowlist=set(hosts), max_pages=3, depth_cap=3)
    _allow_all_robots(crawler, *hosts)

    def _page(request: httpx.Request) -> httpx.Response:
        del request
        links = "".join(f'<a href="/p{i}.html">{i}</a>' for i in range(5))
        body = f"<html><body>{links}</body></html>".encode()
        return httpx.Response(200, content=body, headers=_HTML)

    async with crawler:
        with respx.mock:
            respx.get(url__regex=r"https://(alpha|beta)\.test/.*").mock(side_effect=_page)
            await asyncio.gather(
                crawler.crawl_host("alpha.test", ["https://alpha.test/"]),
                crawler.crawl_host("beta.test", ["https://beta.test/"]),
            )

    assert len(crawler.all_fetched) == 3
