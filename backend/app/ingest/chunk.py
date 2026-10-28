"""Heading-aware chunking sized for the embedding model (SDD §5.1, ADR-006, issues #6 and #97).

Chunks extracted documents into overlapping, citation-ready segments.
Inputs: the full text and ExtractBlock tuple from extract.py.
Outputs: List[Chunk] with heading_path, char range, url_anchor and token_count.

Chunking strategy:
  1. Heading sections are the outer boundary: a chunk never mixes unrelated sections.
  2. Sections under MIN_SECTION_TOKENS are merged into a neighbouring section under
     the same parent heading instead of being dropped (deadlines, phone numbers and
     office hours live in short sections). Only empty text is discarded.
  3. Sections over TARGET_CHUNK_TOKENS are split on paragraphs, then sentences or
     lines, then a hard token cut, so no chunk can exceed MAX_CHUNK_TOKENS.
  4. Consecutive chunks of a section overlap by at most OVERLAP_TOKENS, taken as
     whole trailing sentences of the previous chunk.
  5. Each chunk's text is an exact slice of the document's full_text, so
     char_start/char_end always locate it.

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


def _hard_cut(text: str, start: int, end: int) -> list[_Span]:
    """Cut text[start:end] every TARGET_CHUNK_TOKENS tokens, preferring word boundaries."""
    encoding = _tokenizer()(
        text[start:end],
        add_special_tokens=False,
        return_offsets_mapping=True,
        verbose=False,
    )
    offsets = encoding["offset_mapping"]
    word_ids = encoding.word_ids()
    spans: list[_Span] = []
    i = 0
    while i < len(offsets):
        j = min(i + TARGET_CHUNK_TOKENS, len(offsets))
        k = j
        while j < len(offsets) and k > i + 1 and word_ids[k] == word_ids[k - 1]:
            k -= 1
        if k > i + 1:
            j = k
        a, b = start + offsets[i][0], start + offsets[j - 1][1]
        spans.append(_Span(a, b, count_tokens(text[a:b])))
        i = j
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
    """Greedily pack pieces into [start, end) windows of at most TARGET_CHUNK_TOKENS."""
    windows: list[tuple[int, int]] = []
    start: int | None = None
    end = 0
    tokens = 0
    for piece in pieces:
        if start is not None and tokens + piece.tokens > TARGET_CHUNK_TOKENS:
            windows.append((start, end))
            overlap = _overlap_start(text, start, end)
            if overlap is not None and overlap[1] + piece.tokens <= TARGET_CHUNK_TOKENS:
                start, tokens = overlap
            else:
                start = None
        if start is None:
            start, tokens = piece.start, 0
        end = piece.end
        tokens += piece.tokens
    if start is not None:
        windows.append((start, end))
    return windows


def _parent(heading_path: str) -> str:
    return heading_path.rpartition(_HEADING_SEPARATOR)[0]


def _related(a: str, b: str) -> bool:
    """True when two headings are siblings, or one is the other's direct parent."""
    return a == b or _parent(a) == _parent(b) or a == _parent(b) or _parent(a) == b


def _common_heading(paths: list[str]) -> str:
    parts = [p.split(_HEADING_SEPARATOR) if p else [] for p in paths]
    common: list[str] = []
    for level in zip(*parts, strict=False):
        if len(set(level)) != 1:
            break
        common.append(level[0])
    return _HEADING_SEPARATOR.join(common)


def _group_blocks(blocks: tuple[ExtractBlock, ...]) -> list[list[ExtractBlock]]:
    """Group adjacent blocks so small sections ride along with a related neighbour."""
    groups: list[list[ExtractBlock]] = []
    group_tokens: list[int] = []
    for block in blocks:
        if not block.text.strip():
            continue
        tokens = count_tokens(block.text)
        if (
            groups
            and (tokens < MIN_SECTION_TOKENS or group_tokens[-1] < MIN_SECTION_TOKENS)
            and group_tokens[-1] + tokens <= TARGET_CHUNK_TOKENS
            and block.char_start == groups[-1][-1].char_end + len("\n\n")
            and _related(groups[-1][-1].heading_path, block.heading_path)
        ):
            groups[-1].append(block)
            group_tokens[-1] += tokens
        else:
            groups.append([block])
            group_tokens.append(tokens)
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
