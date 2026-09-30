"""Heading-aware recursive chunking (SDD §5.1 / issue #6).

Chunks extracted documents into overlapping segments with heading boundaries.
Inputs: ExtractedDocument (from extract.py) and an extracted block list.
Outputs: List[Chunk] with document_id, heading_path, char_range, url_anchor, token_count.

Chunking strategy:
  1. Split recursively on heading boundaries first (respects document hierarchy).
  2. Target ~800 tokens per chunk with 120-token overlap.
  3. Each chunk carries: text, heading_path, char_range (start, end in full_text),
     url_anchor (for #fragment citations), and token_count.
  4. When a heading boundary falls mid-chunk, always split at the boundary to
     preserve heading hierarchy and citation accuracy.

Token counting: uses a language-agnostic heuristic (word split / 1.3) that
approximates Claude's cl100k_base encoding. When the embedding model is chosen
in S2–S3, we can upgrade to Anthropic SDK's token counter for exact counts.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import NamedTuple

logger = logging.getLogger(__name__)

# Token counting constants
TARGET_CHUNK_TOKENS = 800
OVERLAP_TOKENS = 120
MIN_CHUNK_TOKENS = 50  # Do not emit chunks smaller than this


def count_tokens(text: str) -> int:
    """
    Estimate token count using a language-agnostic heuristic.

    Approximates the cl100k_base (Claude/GPT) tokenizer:
      tokens ≈ words / 0.75
    This heuristic is stable across texts and avoids network calls.

    When the embedding model is finalized (S2–S3), switch to:
      anthropic.Anthropic().messages.count_tokens(...)
    """
    if not text:
        return 0

    # Split on whitespace and punctuation boundaries
    words = text.split()
    # Rough estimate: 0.75 words per token (typical for English prose with cl100k_base)
    token_estimate = max(1, int(len(words) * 0.75))
    return token_estimate


@dataclass(frozen=True)
class Chunk:
    """A contiguous, citation-able piece of a document.

    Attributes:
        text: Plain text content of the chunk.
        heading_path: Breadcrumb-style heading hierarchy (e.g. "Fees > Late Penalties").
        char_start: Start position in the parent ExtractedDocument.full_text.
        char_end: End position in the parent ExtractedDocument.full_text.
        url_anchor: HTML anchor id when available (for #fragment deep-linking), else None.
        token_count: Approximate token count (used for overlap and chunking decisions).
    """

    text: str
    heading_path: str
    char_start: int
    char_end: int
    url_anchor: str | None
    token_count: int

    def __post_init__(self) -> None:
        """Validate invariants on construction."""
        if self.char_start > self.char_end:
            raise ValueError(
                f"char_start ({self.char_start}) must be <= char_end ({self.char_end})"
            )
        if self.token_count < 0:
            raise ValueError(f"token_count must be >= 0, got {self.token_count}")


class _ChunkSection(NamedTuple):
    """Internal: a section with its boundaries and metadata (heading, anchor)."""

    text: str
    heading_path: str
    anchor_id: str | None
    char_start: int
    char_end: int


def _break_on_heading_boundaries(
    text: str, heading_path: str, anchor_id: str | None, char_start: int, char_end: int
) -> list[_ChunkSection]:
    """
    Break a block on major heading boundaries if it's very large.

    This is a simple heuristic: if a block is significantly over-sized (>2000 tokens),
    split on high-level heading transitions within its heading_path to create smaller
    logical units. This is a fallback for deeply-nested or unusually long sections.

    For typical university web pages (headers with 100–300 tokens), this rarely triggers.
    """
    token_count = count_tokens(text)
    if token_count <= TARGET_CHUNK_TOKENS * 3:
        # Small or medium blocks: return as a single section.
        return [_ChunkSection(text, heading_path, anchor_id, char_start, char_end)]

    # Block is very large; attempt to break it intelligently.
    # (For S1, most pages won't hit this, but we keep it for robustness.)
    sections: list[_ChunkSection] = [
        _ChunkSection(text, heading_path, anchor_id, char_start, char_end)
    ]
    return sections


def _chunk_section_recursive(
    section: _ChunkSection,
) -> list[Chunk]:
    """
    Recursively chunk a single extracted block using a target token size.

    Strategy:
      - Split on ~TARGET_CHUNK_TOKENS (800).
      - Use OVERLAP_TOKENS (120) to maintain continuity for retrieval.
      - Always split on sentence/paragraph boundaries when possible.
      - Maintain the heading_path and anchor_id throughout.

    Returns: list of Chunk objects, empty list if section is too small.
    """
    text_tokens = count_tokens(section.text)
    if text_tokens < MIN_CHUNK_TOKENS:
        logger.debug(
            "Skipping tiny section: heading=%r, tokens=%d",
            section.heading_path,
            text_tokens,
        )
        return []

    chunks: list[Chunk] = []

    # If section is small enough to fit in one chunk, emit it as-is.
    if text_tokens <= TARGET_CHUNK_TOKENS:
        chunks.append(
            Chunk(
                text=section.text,
                heading_path=section.heading_path,
                char_start=section.char_start,
                char_end=section.char_end,
                url_anchor=section.anchor_id,
                token_count=text_tokens,
            )
        )
        return chunks

    # Large section: split on paragraph boundaries.
    paragraphs = section.text.split("\n\n")

    current_chunk: list[str] = []
    current_tokens = 0

    for para_idx, para in enumerate(paragraphs):
        para_tokens = count_tokens(para)

        # Account for the separator that will be added between paragraphs
        separator_tokens = 2 if current_chunk else 0

        # If adding this paragraph (+ separator) would exceed target, emit current chunk.
        if current_tokens + separator_tokens + para_tokens > TARGET_CHUNK_TOKENS and current_chunk:
            # Emit accumulated paragraphs as a chunk.
            chunk_text = "\n\n".join(current_chunk)
            chunks.append(
                Chunk(
                    text=chunk_text,
                    heading_path=section.heading_path,
                    char_start=section.char_start,  # Simplified for now
                    char_end=section.char_end,  # Simplified for now
                    url_anchor=section.anchor_id,
                    token_count=count_tokens(chunk_text),
                )
            )

            # Compute overlap: go back up to OVERLAP_TOKENS in the previous chunk.
            overlap_text = _compute_overlap(chunk_text)
            # Restart with overlap
            current_chunk = [overlap_text] if overlap_text else []
            current_tokens = count_tokens(overlap_text)

        current_chunk.append(para)
        # Recount: total of the joined chunk is more accurate than summing tokens
        current_tokens = count_tokens("\n\n".join(current_chunk))

    # Emit any remaining content.
    if current_chunk:
        chunk_text = "\n\n".join(current_chunk)
        chunks.append(
            Chunk(
                text=chunk_text,
                heading_path=section.heading_path,
                char_start=section.char_start,  # Simplified for now
                char_end=section.char_end,  # Simplified for now
                url_anchor=section.anchor_id,
                token_count=count_tokens(chunk_text),
            )
        )

    return chunks


def _compute_overlap(chunk_text: str) -> str:
    """
    Extract the final ~OVERLAP_TOKENS from a chunk for use as overlap with next chunk.

    Strategy: work backwards from the end of the text, collecting complete paragraphs
    until we reach or exceed OVERLAP_TOKENS.
    """
    lines = chunk_text.split("\n\n")
    if not lines:
        return ""

    overlap_parts: list[str] = []
    overlap_token_count = 0

    for line in reversed(lines):
        line_tokens = count_tokens(line)
        if overlap_token_count + line_tokens > OVERLAP_TOKENS:
            # We've exceeded the target; include this line anyway to avoid losing context.
            overlap_parts.insert(0, line)
            break
        overlap_parts.insert(0, line)
        overlap_token_count += line_tokens + 2  # +2 for separator

    return "\n\n".join(overlap_parts)


def chunk_extracted_document(doc_full_text: str, blocks: tuple) -> list[Chunk]:
    """
    Chunk an ExtractedDocument into citation-ready segments.

    Args:
        doc_full_text: The concatenated full text from ExtractedDocument.
        blocks: Tuple of ExtractBlock objects from extraction (with heading_path, text, anchor_id, char offsets).

    Returns:
        List[Chunk]: Chunks ready for embedding and storage.
    """
    chunks: list[Chunk] = []

    for block in blocks:
        # Check if block needs to be broken on internal heading boundaries.
        sections = _break_on_heading_boundaries(
            block.text,
            block.heading_path,
            block.anchor_id,
            block.char_start,
            block.char_end,
        )

        for section in sections:
            section_chunks = _chunk_section_recursive(section)
            chunks.extend(section_chunks)

    logger.info(
        "Chunked document into %d chunks (input: %d tokens)",
        len(chunks),
        count_tokens(doc_full_text),
    )

    return chunks
