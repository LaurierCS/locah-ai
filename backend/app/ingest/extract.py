"""Extract main content from crawled HTML and PDF bodies (SDD §5.1).

HTML uses trafilatura for boilerplate stripping; heading hierarchy becomes a
breadcrumb string for the chunker. PDF uses pypdf with one section per page.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from io import BytesIO

import trafilatura
from pypdf import PdfReader
from pypdf.errors import PdfReadError

logger = logging.getLogger(__name__)

_HEADING_TAG_RE = re.compile(
    r"<h([1-6])([^>]*)>(.*?)</h\1>",
    re.IGNORECASE | re.DOTALL,
)
_HEADING_ID_RE = re.compile(r"""\bid\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_MARKDOWN_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)\s*$")
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class ExtractBlock:
    """One logical section: heading boundary (HTML) or page (PDF)."""

    text: str
    heading_path: str
    anchor_id: str | None
    char_start: int
    char_end: int


@dataclass(frozen=True)
class ExtractedDocument:
    """Structured extraction output for chunking and citation anchors."""

    url: str
    title: str | None
    content_type: str
    full_text: str
    blocks: tuple[ExtractBlock, ...]


def extract_document(*, url: str, content_type: str, body: bytes) -> ExtractedDocument | None:
    """Dispatch on content-type. Returns None when nothing usable is extracted."""
    ct = content_type.lower()
    if "application/pdf" in ct:
        return _extract_pdf(url=url, content_type=content_type, body=body)
    if "text/html" in ct:
        return _extract_html(url=url, content_type=content_type, body=body)
    logger.warning("Unsupported content-type for extraction: %s (%s)", content_type, url)
    return None


def _normalize_heading_text(text: str) -> str:
    """Collapse whitespace and casefold for HTML ↔ markdown heading matching."""
    stripped = _TAG_RE.sub("", text)
    return " ".join(stripped.split()).casefold()


def _build_anchor_map(html: str) -> dict[str, str]:
    """Map normalized heading text to HTML id (first id wins on duplicates)."""
    anchors: dict[str, str] = {}
    for match in _HEADING_TAG_RE.finditer(html):
        attrs = match.group(2)
        id_match = _HEADING_ID_RE.search(attrs)
        if not id_match:
            continue
        key = _normalize_heading_text(match.group(3))
        if key and key not in anchors:
            anchors[key] = id_match.group(1)
    return anchors


def _plain_text(fragment: str) -> str:
    """Strip tags and collapse whitespace."""
    text = _TAG_RE.sub(" ", fragment)
    return " ".join(text.split())


def _html_main_scope(html: str) -> str:
    """Prefer <main> or <article> so nav/footer outside those tags are ignored."""
    for tag in ("main", "article"):
        match = re.search(rf"<{tag}[^>]*>(.*)</{tag}>", html, re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1)
    return html


def _sectionize_html_headings(scoped_html: str) -> list[tuple[str, str, str | None]]:
    """Build sections from HTML heading tags when trafilatura omits markdown `#` lines."""
    headings = list(_HEADING_TAG_RE.finditer(scoped_html))
    if not headings:
        body = _plain_text(scoped_html)
        return [("", body, None)] if body else []

    sections: list[tuple[str, str, str | None]] = []
    stack: list[tuple[int, str]] = []

    pre = scoped_html[: headings[0].start()]
    pre_text = _plain_text(pre)
    if pre_text:
        sections.append(("", pre_text, None))

    for index, heading in enumerate(headings):
        level = int(heading.group(1))
        attrs = heading.group(2)
        title = _plain_text(heading.group(3))
        id_match = _HEADING_ID_RE.search(attrs)
        anchor_id = id_match.group(1) if id_match else None

        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        path = " > ".join(section_title for _, section_title in stack)

        body_start = heading.end()
        body_end = headings[index + 1].start() if index + 1 < len(headings) else len(scoped_html)
        body = _plain_text(scoped_html[body_start:body_end])
        if body:
            sections.append((path, body, anchor_id))

    return sections


def _sectionize_markdown(
    markdown: str,
    anchor_map: dict[str, str],
) -> list[tuple[str, str, str | None]]:
    """Return (heading_path, body_text, anchor_id) tuples without char offsets yet."""
    sections: list[tuple[str, str, str | None]] = []
    stack: list[tuple[int, str]] = []
    current_lines: list[str] = []
    current_anchor: str | None = None

    def flush() -> None:
        nonlocal current_lines, current_anchor
        body = "\n".join(current_lines).strip()
        if body:
            path = " > ".join(title for _, title in stack)
            sections.append((path, body, current_anchor))
        current_lines = []

    for line in markdown.splitlines():
        heading_match = _MARKDOWN_HEADING_RE.match(line)
        if heading_match:
            flush()
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            normalized = _normalize_heading_text(title)
            current_anchor = anchor_map.get(normalized)
            continue
        current_lines.append(line)

    flush()
    return sections


def _blocks_with_offsets(
    sections: list[tuple[str, str, str | None]],
) -> tuple[str, tuple[ExtractBlock, ...]]:
    """Join section bodies and assign char_start/char_end in full_text."""
    if not sections:
        return "", ()

    blocks: list[ExtractBlock] = []
    parts: list[str] = []
    offset = 0
    for i, (heading_path, text, anchor_id) in enumerate(sections):
        if i > 0:
            parts.append("\n\n")
            offset += 2
        char_start = offset
        parts.append(text)
        offset += len(text)
        blocks.append(
            ExtractBlock(
                text=text,
                heading_path=heading_path,
                anchor_id=anchor_id,
                char_start=char_start,
                char_end=offset,
            )
        )
    full_text = "".join(parts)
    return full_text, tuple(blocks)


def _extract_html(*, url: str, content_type: str, body: bytes) -> ExtractedDocument | None:
    html = body.decode("utf-8", errors="replace")
    metadata = trafilatura.extract_metadata(html, default_url=url)
    title = metadata.title if metadata and metadata.title else None

    markdown = trafilatura.extract(
        html,
        url=url,
        output_format="markdown",
        include_comments=False,
        include_tables=True,
    )
    if not markdown or not markdown.strip():
        logger.warning("No main content extracted from HTML: %s", url)
        return None

    anchor_map = _build_anchor_map(html)
    has_markdown_headings = any(_MARKDOWN_HEADING_RE.match(line) for line in markdown.splitlines())
    if has_markdown_headings:
        sections = _sectionize_markdown(markdown, anchor_map)
    else:
        # Trafilatura often emits plain lines for headings; use HTML structure instead.
        sections = _sectionize_html_headings(_html_main_scope(html))

    if not sections:
        sections = [("", markdown.strip(), None)]

    full_text, blocks = _blocks_with_offsets(sections)
    if not full_text.strip():
        logger.warning("Empty text after HTML sectionization: %s", url)
        return None

    return ExtractedDocument(
        url=url,
        title=title,
        content_type=content_type,
        full_text=full_text,
        blocks=blocks,
    )


def _extract_pdf(*, url: str, content_type: str, body: bytes) -> ExtractedDocument | None:
    try:
        reader = PdfReader(BytesIO(body))
    except PdfReadError as exc:
        logger.warning("Failed to read PDF %s: %s", url, exc)
        return None

    title: str | None = None
    if reader.metadata and reader.metadata.title:
        title = str(reader.metadata.title)

    sections: list[tuple[str, str, str | None]] = []
    for page_num, page in enumerate(reader.pages, start=1):
        raw = page.extract_text() or ""
        page_text = raw.strip()
        if not page_text:
            continue
        labeled = f"Page {page_num}\n\n{page_text}"
        sections.append((f"Page {page_num}", labeled, None))

    if not sections:
        logger.warning("No text extracted from PDF: %s", url)
        return None

    full_text, blocks = _blocks_with_offsets(sections)
    return ExtractedDocument(
        url=url,
        title=title,
        content_type=content_type,
        full_text=full_text,
        blocks=blocks,
    )
