"""Unit tests for url_policy — pure functions, no network, no DB."""

import pytest

from app.ingest.url_policy import is_crawlable_link, is_error_document_url, is_persistable_fetch


# ---------------------------------------------------------------------------
# is_crawlable_link
# ---------------------------------------------------------------------------


class TestIsCrawlableLink:
    def test_normal_html_page_allowed(self) -> None:
        assert is_crawlable_link("https://students.wlu.ca/academics/advising/index.html")

    def test_academic_calendar_allowed(self) -> None:
        assert is_crawlable_link(
            "https://academic-calendar.wlu.ca/section.php?cal=1&s=1156&y=92"
        )

    def test_css_rejected(self) -> None:
        assert not is_crawlable_link("https://www.wlu.ca/_ato/dist/css/ato.min.css?v=3")

    def test_min_css_suffix_rejected(self) -> None:
        assert not is_crawlable_link("https://www.wlu.ca/assets/theme.min.css")

    def test_js_rejected(self) -> None:
        assert not is_crawlable_link("https://www.wlu.ca/assets/app.js")

    def test_map_rejected(self) -> None:
        assert not is_crawlable_link("https://www.wlu.ca/assets/app.js.map")

    def test_svg_rejected(self) -> None:
        assert not is_crawlable_link("https://www.wlu.ca/images/logo.svg")

    def test_ato_prefix_rejected(self) -> None:
        assert not is_crawlable_link("https://www.wlu.ca/_ato/dist/css/custom.css")

    def test_dist_prefix_rejected(self) -> None:
        assert not is_crawlable_link("https://www.wlu.ca/dist/bundle.js")

    def test_404_path_prefix_rejected(self) -> None:
        assert not is_crawlable_link(
            "https://www.wlu.ca/404/404.html?req=%2Fstudent-advising%2Findex.html"
        )

    def test_woff_font_rejected(self) -> None:
        assert not is_crawlable_link("https://www.wlu.ca/fonts/laurier.woff2")

    def test_pdf_page_allowed(self) -> None:
        # .pdf extension is a valid content type we crawl
        # (content-type filter handles actual rejection if needed)
        assert is_crawlable_link("https://students.wlu.ca/docs/handbook.pdf")

    def test_relative_url_rejected(self) -> None:
        # Relative URLs are never enqueued — the crawler only sees absolute URLs
        # (normalize_url resolves them), but the policy function guards defensively.
        assert not is_crawlable_link("/relative/path/page.html")


# ---------------------------------------------------------------------------
# is_error_document_url
# ---------------------------------------------------------------------------


class TestIsErrorDocumentUrl:
    def test_laurier_404_helper_path(self) -> None:
        assert is_error_document_url(
            "https://www.wlu.ca/404/404.html"
            "?req=%2Fstudent-advising%2Findex.html"
            "%3Fref%3Dstudent-advising%252Findex.html"
        )

    def test_404_path_without_query(self) -> None:
        assert is_error_document_url("https://www.wlu.ca/404/404.html")

    def test_req_query_param_alone(self) -> None:
        # Some Laurier pages redirect to a helper with just ?req=
        assert is_error_document_url("https://www.wlu.ca/helper?req=%2Fsome%2Fpath")

    def test_normal_page_not_error(self) -> None:
        assert not is_error_document_url(
            "https://students.wlu.ca/academics/support-and-advising/index.html"
        )

    def test_academic_calendar_not_error(self) -> None:
        assert not is_error_document_url(
            "https://academic-calendar.wlu.ca/section.php?cal=1&s=1156&y=92"
        )

    def test_empty_string(self) -> None:
        assert not is_error_document_url("")

    def test_standalone_404_html(self) -> None:
        assert is_error_document_url("https://www.wlu.ca/404.html")


# ---------------------------------------------------------------------------
# is_persistable_fetch
# ---------------------------------------------------------------------------


class TestIsPersistableFetch:
    def test_good_200_fetch(self) -> None:
        assert is_persistable_fetch(b"<html>content</html>", "abc123hash", 200)

    def test_empty_body_rejected(self) -> None:
        assert not is_persistable_fetch(b"", "abc123hash", 200)

    def test_none_body_rejected(self) -> None:
        assert not is_persistable_fetch(None, "abc123hash", 200)

    def test_empty_hash_rejected(self) -> None:
        assert not is_persistable_fetch(b"<html>content</html>", "", 200)

    def test_none_hash_rejected(self) -> None:
        assert not is_persistable_fetch(b"<html>content</html>", None, 200)

    def test_304_rejected(self) -> None:
        assert not is_persistable_fetch(b"", "", 304)

    def test_non_200_status_rejected(self) -> None:
        assert not is_persistable_fetch(b"content", "hash", 301)

    def test_none_status_rejected(self) -> None:
        assert not is_persistable_fetch(b"content", "hash", None)
