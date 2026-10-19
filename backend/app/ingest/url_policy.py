"""URL admission policy for the ingest crawler (SDD §5.1 / INV-1).

Three pure, unit-testable predicates decide what the crawler fetches, follows,
and persists — keeping these decisions out of the 400-line crawler.py.

    is_crawlable_link(url)      — should a discovered link be enqueued?
    is_error_document_url(url)  — does the final URL indicate a server error page?
    is_persistable_fetch(...)   — is a completed fetch worth writing to `documents`?
"""

from __future__ import annotations

from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Denylist for link enqueueing — paths / extensions that are never useful content
# ---------------------------------------------------------------------------

# Path *prefixes* that are always assets/infrastructure, not student content.
_DENYLIST_PATH_PREFIXES: tuple[str, ...] = (
    "/_ato/",
    "/dist/",
    "/404/",
    "/.well-known/",
)

# File *suffixes* whose content is never indexable text.
_DENYLIST_EXTENSIONS: tuple[str, ...] = (
    ".css",
    ".js",
    ".min.css",
    ".min.js",
    ".map",
    ".ico",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".pdf.js",  # viewer wrappers
)

# ---------------------------------------------------------------------------
# Laurier error-page indicators on the *final* (post-redirect) URL
# ---------------------------------------------------------------------------

# Path segments that appear in Laurier's generic 404 helper URLs.
_ERROR_PATH_SEGMENTS: tuple[str, ...] = (
    "/404/404.html",
    "/404.html",
    "/error/",
)

# Query parameters that indicate the server rendered an error page.
_ERROR_QUERY_PARAMS: tuple[str, ...] = (
    "req=",  # Laurier's 404 helper embeds the bad path as ?req=...
)


def is_crawlable_link(url: str) -> bool:
    """Return True when a discovered link should be enqueued for crawling.

    Rejects asset files, infrastructure paths, and Laurier error-page helpers
    before spending a network round-trip on them.  Also rejects relative URLs
    and anything without an http(s) scheme (the crawler only handles absolute
    URLs; normalize_url is the primary guard, but this is a defensive belt).
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return False

    if parsed.scheme not in ("http", "https"):
        return False

    path = parsed.path.lower()

    # Reject known asset/infrastructure path prefixes.
    if any(path.startswith(prefix) for prefix in _DENYLIST_PATH_PREFIXES):
        return False

    # Reject static asset extensions (check path without query string).
    if any(path.endswith(ext) for ext in _DENYLIST_EXTENSIONS):
        return False

    return True


def is_error_document_url(url: str) -> bool:
    """Return True when a URL (typically the *final* URL after redirects) looks
    like a Laurier error or 404 helper page.

    We check both the path and query string so that both patterns are caught:
      - /404/404.html (direct path)
      - /404/404.html?req=%2Fstudent-advising%2Findex.html (redirect destination)
    """
    if not url:
        return False

    try:
        parsed = urlparse(url)
    except ValueError:
        return False

    path = parsed.path.lower()
    query = parsed.query.lower()

    if any(seg in path for seg in _ERROR_PATH_SEGMENTS):
        return True

    # A ?req= param almost always means Laurier's 404 helper received a bad path.
    if any(param in query for param in _ERROR_QUERY_PARAMS):
        return True

    return False


def is_persistable_fetch(
    body: bytes | None,
    content_hash: str | None,
    http_status: int | None,
) -> bool:
    """Return True only when a fetch produced content that is worth storing.

    Guards against persisting empty-body CSS/JS/304 results as document rows
    that later inflate the `documents` table with no corresponding chunks.
    """
    return (
        http_status == 200
        and bool(body)
        and bool(content_hash)
    )
