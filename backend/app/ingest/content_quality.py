"""Post-extraction content quality checks (SDD §5.1).

Two responsibilities:

    is_usable_extracted_text(text)   — decides whether extracted text is
                                       rich enough to be worth chunking/embedding.

    deactivate_document(session, url) — marks a document inactive and deletes
                                        its chunks so it drops out of retrieval
                                        without losing the audit row.

Keeping this in a dedicated module makes it easy to tighten the heuristics
(MIN_DOCUMENT_TOKENS, boilerplate patterns) without touching pipeline.py.
"""

from __future__ import annotations

import logging
import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.ingest.chunk import count_tokens

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Token threshold
# ---------------------------------------------------------------------------

# A document must produce at least this many tokens of real text after
# trafilatura stripping.  Anything below this is almost certainly a navigation
# shell, consent banner, or empty redirect page.
# count_tokens() counts real bge-base tokens, about 1.0–1.3 per English word, so
# 80 tokens ≈ 65 words of prose (the same floor as the old word heuristic) —
# enough to reject menus/shells but accept short real pages.
MIN_DOCUMENT_TOKENS = 80

# ---------------------------------------------------------------------------
# Boilerplate fingerprints — cookie consent / CMS navigation shells
# ---------------------------------------------------------------------------

# These phrases appear at or near the start of pages where trafilatura
# managed to extract *something* but the "something" is OneTrust /
# accessibility boilerplate rather than actual student-facing content.
_BOILERPLATE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"by selecting accept all", re.IGNORECASE),
    re.compile(r"we use cookies to provide you with the best", re.IGNORECASE),
    re.compile(r"consent to our use of cookies", re.IGNORECASE),
    re.compile(r"privacy preference center", re.IGNORECASE),
    re.compile(r"strictly necessary cookies", re.IGNORECASE),
    re.compile(r"performance cookies", re.IGNORECASE),
    re.compile(r"cookie policy", re.IGNORECASE),
    # OneTrust / Cookiebot JS-injected copy that leaks into trafilatura output
    re.compile(r"onetrust", re.IGNORECASE),
]

# How many boilerplate patterns can match before we reject.
# 1 is sufficient — a real page never leads with cookie consent copy.
_MAX_BOILERPLATE_MATCHES = 0


def is_usable_extracted_text(text: str) -> bool:
    """Return True when extracted text is substantive and not boilerplate.

    Two gates:
      1. Token count ≥ MIN_DOCUMENT_TOKENS — rejects navigation shells and
         empty redirect pages.
      2. No boilerplate fingerprints — rejects consent banner copy that
         trafilatura occasionally extracts from pages with thin <main> content.
    """
    if not text or not text.strip():
        return False

    if count_tokens(text) < MIN_DOCUMENT_TOKENS:
        return False

    boilerplate_hits = sum(1 for p in _BOILERPLATE_PATTERNS if p.search(text))
    return boilerplate_hits <= _MAX_BOILERPLATE_MATCHES


async def deactivate_document(session: AsyncSession, url: str) -> None:
    """Mark a document inactive and delete its chunks.

    The document row is kept for audit purposes (we can see what was tried and
    why it failed).  Setting is_active=False removes it from retrieval
    automatically because search.py already filters WHERE d.is_active.

    Chunks are deleted rather than flagged so they do not waste pgvector index
    space for vectors that will never be retrieved.
    """
    from sqlalchemy import text

    # Delete chunks first (FK reference to documents).
    delete_chunks = text(
        "DELETE FROM chunks WHERE document_id = (SELECT id FROM documents WHERE url = :url)"
    )
    deactivate = text("UPDATE documents SET is_active = FALSE WHERE url = :url")
    await session.execute(delete_chunks, {"url": url})
    await session.execute(deactivate, {"url": url})
    # Caller is responsible for committing; this keeps the helper composable
    # with bulk deactivation loops that want a single commit at the end.
    logger.info(f"Deactivated document and deleted chunks: {url}")
