"""Heading-aware chunking sized for the embedding model (SDD §5.1, ADR-006, issues #6 and #97).

Chunks extracted documents into overlapping, citation-ready segments.
Inputs: the full text and ExtractBlock tuple from extract.py.
Outputs: List[Chunk] with heading_path, char range, url_anchor and token_count.

Chunking strategy:
  1. Heading sections are the outer boundary: a chunk never mixes unrelated sections.
     Top-level headings have no parent, so they are not merged with each other.
  2. Sections under MIN_SECTION_TOKENS are merged into a neighbouring section under
     the same parent heading instead of being dropped (deadlines, phone numbers and
     office hours live in short sections). Only empty text is discarded. A merge
     only happens when the joined text still fits in one target chunk.
  3. Sections over TARGET_CHUNK_TOKENS are split on paragraphs, then sentences or
     lines, then a hard token cut, so no chunk can exceed MAX_CHUNK_TOKENS.
     Budgets are the token count of the chunk text itself, separators included.
  4. Consecutive chunks of a section overlap by at most OVERLAP_TOKENS, taken as
     whole trailing sentences of the previous chunk.
  5. Each chunk's text is an exact slice of the document's full_text, so
     char_start/char_end always locate it. Hard cuts cover the source without gaps.

Token counting: uses the embedding model's own tokenizer (bge-base-en-v1.5), because
the limit that matters is what the embedder reads. bge reads at most 512 tokens,
including the [CLS] and [SEP] it adds, and truncates anything past that.
"""

from __future__ import annotations

import functools
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.core.config import settings
from app.ingest.extract import ExtractBlock

if TYPE_CHECKING:
    from transformers import PreTrainedTokenizerBase

logger = logging.getLogger(__name__)

# The embedder's hard input limit, including the 2 special tokens it adds.
EMBED_MAX_SEQ_LENGTH = 512
MAX_CHUNK_TOKENS = EMBED_MAX_SEQ_LENGTH - 2
# Below the limit, leaving headroom for heading/title context prepended at embed time.
TARGET_CHUNK_TOKENS = 350
OVERLAP_TOKENS = 50
# Sections smaller than this are merged with a related neighbour when one fits.
MIN_SECTION_TOKENS = 50

_PARAGRAPH_BREAK_RE = re.compile(r"\n\s*\n")
_SENTENCE_BREAK_RE = re.compile(r"(?<=[.!?])\s+|\s*\n\s*")
_HEADING_SEPARATOR = " > "


@functools.cache
def _tokenizer() -> PreTrainedTokenizerBase:
    """Load (once per process) the tokenizer that ships with the embedding model."""
    from transformers import AutoTokenizer

    return AutoTokenizer.from_pretrained(settings.embedding_model)


def count_tokens(text: str) -> int:
    """Count embedding-model tokens in *text*, excluding the special tokens."""
    if not text:
        return 0
    return len(_tokenizer().encode(text, add_special_tokens=False, verbose=False))


@dataclass(frozen=True)
class Chunk:
    """A contiguous, citation-able piece of a document.

    Attributes:
        text: Plain text content of the chunk.
        heading_path: Breadcrumb-style heading hierarchy (e.g. "Fees > Late Penalties").
        char_start: Start position in the parent ExtractedDocument.full_text.
        char_end: End position in the parent ExtractedDocument.full_text.
        url_anchor: HTML anchor id when available (for #fragment deep-linking), else None.
        token_count: Embedding-model token count of text (special tokens excluded).
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


@dataclass(frozen=True)
class _Span:
    """Internal: a [start, end) slice of a section's text and its token count."""

    start: int
    end: int
    tokens: int


def _split_spans(
    text: str, start: int, end: int, pattern: re.Pattern[str]
) -> list[tuple[int, int]]:
    """Split text[start:end] at *pattern*; return whitespace-trimmed, non-empty spans."""
    bounds: list[tuple[int, int]] = []
    pos = start
    for match in pattern.finditer(text, start, end):
        bounds.append((pos, match.start()))
        pos = match.end()
    bounds.append((pos, end))

    spans: list[tuple[int, int]] = []
    for a, b in bounds:
        while a < b and text[a].isspace():
            a += 1
        while b > a and text[b - 1].isspace():
            b -= 1
        if a < b:
            spans.append((a, b))
    return spans


def _token_layout(text: str, start: int, end: int) -> list[tuple[int, int, int | None]]:
    """Return (abs_start, abs_end, word_id) for each real token in text[start:end]."""
    encoding = _tokenizer()(
        text[start:end],
        add_special_tokens=False,
        return_offsets_mapping=True,
        verbose=False,
    )
    offsets = list(encoding["offset_mapping"])
    raw_words = encoding.word_ids()
    word_ids = list(raw_words) if raw_words is not None else []
    if len(word_ids) != len(offsets):
        word_ids = [None] * len(offsets)
    layout: list[tuple[int, int, int | None]] = []
    for (rel_start, rel_end), word_id in zip(offsets, word_ids, strict=True):
        if rel_start < rel_end:
            layout.append((start + rel_start, start + rel_end, word_id))
    return layout


def _word_boundary(tokens: list[tuple[int, int, int | None]], j: int) -> int:
    """Pull *j* back so the cut is not mid-word. Always leaves at least one token."""
    if j >= len(tokens):
        return j
    k = j
    while k > 1 and tokens[k][2] is not None and tokens[k][2] == tokens[k - 1][2]:
        k -= 1
    if k > 1 and tokens[k][2] != tokens[k - 1][2]:
        return k
    return j


def _hard_cut(text: str, start: int, end: int) -> list[_Span]:
    """Cut text[start:end] into contiguous spans of at most TARGET_CHUNK_TOKENS.

    Cuts prefer word boundaries. Characters the tokenizer does not emit (spaces
    between tokens, and any tail) stay in a span, so the slices cover [start, end)
    exactly and a citation never drops source text. The token count is measured
    on the slice itself: retokenizing a token window can be larger than the
    window, and that count is what the embedder will see.
    """
    spans: list[_Span] = []
    cursor = start
    while cursor < end:
        remaining = count_tokens(text[cursor:end])
        if remaining <= TARGET_CHUNK_TOKENS:
            spans.append(_Span(cursor, end, remaining))
            break
        tokens = _token_layout(text, cursor, end)
        if not tokens:
            spans.append(_Span(cursor, cursor + 1, count_tokens(text[cursor : cursor + 1])))
            cursor += 1
            continue
        j = _word_boundary(tokens, min(TARGET_CHUNK_TOKENS, len(tokens)))
        cut = cursor
        while j >= 1:
            # Include the gap before the next token so it is not dropped between spans.
            candidate = tokens[j][0] if j < len(tokens) else end
            if candidate > cursor and count_tokens(text[cursor:candidate]) <= TARGET_CHUNK_TOKENS:
                cut = candidate
                break
            j -= 1
        if cut <= cursor:
            cut = cursor + 1
        spans.append(_Span(cursor, cut, count_tokens(text[cursor:cut])))
        cursor = cut
    return spans


def _fit(text: str, start: int, end: int) -> list[_Span]:
    """Return spans covering text[start:end], each at most TARGET_CHUNK_TOKENS."""
    tokens = count_tokens(text[start:end])
    if tokens <= TARGET_CHUNK_TOKENS:
        return [_Span(start, end, tokens)]
    sentences = _split_spans(text, start, end, _SENTENCE_BREAK_RE)
    if len(sentences) > 1:
        return [span for a, b in sentences for span in _fit(text, a, b)]
    return _hard_cut(text, start, end)


def _pieces(text: str) -> list[_Span]:
    """Split text into packable pieces: paragraphs, then sentences, then hard cuts."""
    return [
        span
        for a, b in _split_spans(text, 0, len(text), _PARAGRAPH_BREAK_RE)
        for span in _fit(text, a, b)
    ]


def _overlap_start(text: str, start: int, end: int) -> tuple[int, int] | None:
    """Return (start, tokens) of the longest run of trailing sentences of text[start:end]
    within OVERLAP_TOKENS, or None. The whole chunk is never reused as overlap."""
    best: tuple[int, int] | None = None
    for a, _ in reversed(_split_spans(text, start, end, _SENTENCE_BREAK_RE)[1:]):
        tokens = count_tokens(text[a:end])
        if tokens > OVERLAP_TOKENS:
            break
        best = (a, tokens)
    return best


def _pack(text: str, pieces: list[_Span]) -> list[tuple[int, int]]:
    """Greedily pack pieces into [start, end) windows of at most TARGET_CHUNK_TOKENS.

    The budget is the token count of the window text, not the sum of piece
    counts. Piece sums ignore the separators the window still contains, and a
    page of short lines can blow past the embedder's limit that way.
    """
    windows: list[tuple[int, int]] = []
    start: int | None = None
    end = 0
    for piece in pieces:
        if start is not None and count_tokens(text[start : piece.end]) > TARGET_CHUNK_TOKENS:
            windows.append((start, end))
            overlap = _overlap_start(text, start, end)
            if (
                overlap is not None
                and count_tokens(text[overlap[0] : piece.end]) <= TARGET_CHUNK_TOKENS
            ):
                start = overlap[0]
            else:
                start = None
        if start is None:
            start = piece.start
        end = piece.end
    if start is not None:
        windows.append((start, end))
    return windows


def _parent(heading_path: str) -> str | None:
    """Parent heading, or None when *heading_path* is top-level."""
    parent, sep, _child = heading_path.rpartition(_HEADING_SEPARATOR)
    if not sep:
        return None
    return parent


def _related(a: str, b: str) -> bool:
    """True when two headings match, are siblings, or one is the other's direct parent.

    A missing parent is not a shared parent. Treating "" as one would merge
    unrelated top-level sections (Fees with Housing) and drop both headings.
    """
    if a == b:
        return True
    parent_a = _parent(a)
    parent_b = _parent(b)
    if parent_a is not None and parent_a == parent_b:
        return True
    return (parent_b is not None and a == parent_b) or (parent_a is not None and b == parent_a)


def _common_heading(paths: list[str]) -> str:
    parts = [p.split(_HEADING_SEPARATOR) if p else [] for p in paths]
    common: list[str] = []
    for level in zip(*parts, strict=False):
        if len(set(level)) != 1:
            break
        common.append(level[0])
    return _HEADING_SEPARATOR.join(common)


def _can_merge(group: list[ExtractBlock], block: ExtractBlock) -> bool:
    """True when *block* should ride along with *group* as one target-sized chunk."""
    previous = group[-1]
    if block.char_start != previous.char_end + len("\n\n"):
        return False
    if not _related(previous.heading_path, block.heading_path):
        return False
    group_text = "\n\n".join(part.text for part in group)
    group_tokens = count_tokens(group_text)
    block_tokens = count_tokens(block.text)
    if group_tokens >= MIN_SECTION_TOKENS and block_tokens >= MIN_SECTION_TOKENS:
        return False
    # Summing the two counts ignores the joiner and can exceed the target.
    return count_tokens(f"{group_text}\n\n{block.text}") <= TARGET_CHUNK_TOKENS


def _group_blocks(blocks: tuple[ExtractBlock, ...]) -> list[list[ExtractBlock]]:
    """Group adjacent blocks so small sections ride along with a related neighbour."""
    groups: list[list[ExtractBlock]] = []
    for block in blocks:
        if not block.text.strip():
            continue
        if groups and _can_merge(groups[-1], block):
            groups[-1].append(block)
        else:
            groups.append([block])
    return groups


def chunk_extracted_document(doc_full_text: str, blocks: tuple[ExtractBlock, ...]) -> list[Chunk]:
    """
    Chunk an ExtractedDocument into citation-ready segments.

    Args:
        doc_full_text: The concatenated full text from ExtractedDocument.
        blocks: Tuple of ExtractBlock objects from extraction (with heading_path, text, anchor_id, char offsets).

    Returns:
        List[Chunk]: Chunks ready for embedding and storage.
    """
    chunks: list[Chunk] = []

    for group in _group_blocks(blocks):
        # Blocks are joined in full_text with "\n\n", so offsets into this joined
        # text map onto full_text by adding the first block's char_start.
        text = "\n\n".join(block.text for block in group)
        base = group[0].char_start
        heading_path = _common_heading([block.heading_path for block in group])
        anchor = next((block.anchor_id for block in group if block.anchor_id), None)

        for start, end in _pack(text, _pieces(text)):
            chunk_text = text[start:end]
            chunks.append(
                Chunk(
                    text=chunk_text,
                    heading_path=heading_path,
                    char_start=base + start,
                    char_end=base + end,
                    url_anchor=anchor,
                    token_count=count_tokens(chunk_text),
                )
            )

    logger.info(
        "Chunked document into %d chunks (input: %d tokens)",
        len(chunks),
        count_tokens(doc_full_text),
    )

    return chunks
