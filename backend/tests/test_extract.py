"""Tests for HTML/PDF content extraction (SDD §5.1 / issue #5)."""

from __future__ import annotations

import hashlib
from io import BytesIO

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.ingest.extract import extract_document


def _make_pdf_with_pages(*labels: str) -> bytes:
    """Build a minimal PDF with one text line per page (for pypdf extract_text)."""
    writer = PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    for label in labels:
        writer.add_blank_page(width=612, height=792)
        page = writer.pages[-1]
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 100 700 Td ({label}) Tj ET".encode())
        page[NameObject("/Contents")] = stream
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
        )
    buf = BytesIO()
    writer.write(buf)
    return buf.getvalue()


REGISTRAR_HTML = """
<!DOCTYPE html>
<html><head><title>Registrar Fees</title></head>
<body>
<nav><a href="/home">Home</a> Cookie banner accept</nav>
<main>
<article>
<h2 id="registrar">Registrar</h2>
<p>Main fee policy paragraph for students.</p>
<h3 id="fees">Fees</h3>
<p>Undergraduate fee details here.</p>
</article>
</main>
<footer>Copyright Laurier footer text</footer>
</body></html>
"""


def test_html_strips_nav_and_keeps_main_content() -> None:
    doc = extract_document(
        url="https://www.wlu.ca/registrar",
        content_type="text/html; charset=utf-8",
        body=REGISTRAR_HTML.encode(),
    )
    assert doc is not None
    assert doc.title == "Registrar Fees"
    combined = doc.full_text.lower()
    assert "cookie banner" not in combined
    assert "footer text" not in combined
    assert "main fee policy paragraph" in combined


def test_html_nested_headings_breadcrumb_and_anchors() -> None:
    doc = extract_document(
        url="https://www.wlu.ca/registrar",
        content_type="text/html",
        body=REGISTRAR_HTML.encode(),
    )
    assert doc is not None
    assert len(doc.blocks) == 2
    assert doc.blocks[0].heading_path == "Registrar"
    assert doc.blocks[0].anchor_id == "registrar"
    assert doc.blocks[1].heading_path == "Registrar > Fees"
    assert doc.blocks[1].anchor_id == "fees"


def test_html_prose_only_single_block() -> None:
    html = "<html><body><main><p>Standalone paragraph without headings.</p></main></body></html>"
    doc = extract_document(
        url="https://www.wlu.ca/plain",
        content_type="text/html",
        body=html.encode(),
    )
    assert doc is not None
    assert len(doc.blocks) == 1
    assert doc.blocks[0].heading_path == ""
    assert "Standalone paragraph" in doc.blocks[0].text


def test_pdf_page_numbered_sections() -> None:
    pdf_bytes = _make_pdf_with_pages("First page body", "Second page body")
    doc = extract_document(
        url="https://www.wlu.ca/forms/sample.pdf",
        content_type="application/pdf",
        body=pdf_bytes,
    )
    assert doc is not None
    assert len(doc.blocks) == 2
    assert doc.blocks[0].heading_path == "Page 1"
    assert doc.blocks[1].heading_path == "Page 2"
    assert "First page body" in doc.blocks[0].text
    assert "Second page body" in doc.blocks[1].text
    assert doc.blocks[0].char_start == 0
    assert doc.blocks[0].char_end < doc.blocks[1].char_start


def test_empty_html_returns_none() -> None:
    assert (
        extract_document(
            url="https://www.wlu.ca/empty",
            content_type="text/html",
            body=b"<html><body></body></html>",
        )
        is None
    )


def test_unsupported_content_type_returns_none() -> None:
    assert (
        extract_document(
            url="https://www.wlu.ca/file.bin",
            content_type="application/octet-stream",
            body=b"\x00\x01",
        )
        is None
    )


@pytest.mark.asyncio
async def test_crawler_hashes_raw_pdf_bytes() -> None:
    """CrawlResult.body and content_hash must reflect resp.content, not decoded text."""
    import httpx
    import respx

    from app.core.config import settings
    from app.ingest.crawler import CrawlerConfig, CrawlerState

    pdf_bytes = _make_pdf_with_pages("Hash probe")
    expected_hash = hashlib.sha256(pdf_bytes).hexdigest()

    config = CrawlerConfig(
        allowlist=settings.allowed_hosts,
        user_agent=settings.crawl_user_agent,
        delay_seconds=settings.crawl_delay_seconds,
        max_pages=settings.crawl_max_pages,
        depth_cap=1,
        content_types=["text/html", "application/pdf"],
    )
    crawler = CrawlerState(config)
    url = "https://www.wlu.ca/documents/sample.pdf"

    async with crawler:
        with respx.mock:
            respx.get(url).mock(
                return_value=httpx.Response(
                    200,
                    content=pdf_bytes,
                    headers={"content-type": "application/pdf"},
                )
            )
            body, content_hash, status, _etag, content_type = await crawler.fetch_and_hash(url)

    assert status == 200
    assert body == pdf_bytes
    assert content_hash == expected_hash
    assert "application/pdf" in content_type
