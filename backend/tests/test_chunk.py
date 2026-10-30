"""Tests for the heading-aware chunker (SDD §5.1 / issues #6 and #97).

Assertions are made on what the embedding model actually receives: token counts
use the real bge-base-en-v1.5 tokenizer (special tokens included where the limit
is checked), so a chunk that passes here is a chunk the model reads in full.

Verifies:
  - No chunk exceeds the model's 512-token input, whatever the input shape.
  - Short sections are merged into a related neighbour, never dropped.
  - Large sections split on paragraphs, then sentences, then a hard token cut.
  - Overlap between consecutive chunks is capped in tokens.
  - char_start/char_end locate each chunk's text exactly in full_text.
"""

import itertools

import pytest

from app.ingest.chunk import (
    EMBED_MAX_SEQ_LENGTH,
    MAX_CHUNK_TOKENS,
    OVERLAP_TOKENS,
    TARGET_CHUNK_TOKENS,
    Chunk,
    _tokenizer,
    chunk_extracted_document,
    count_tokens,
)
from app.ingest.extract import ExtractBlock, extract_document

SENTENCE = (
    "Students who wish to change their program must meet with an academic advisor "
    "before the end of the term and submit the required form to the Office of the Registrar. "
)
DEADLINE = "The last day to drop a Fall course without academic penalty is November 8."


def _model_tokens(text: str) -> int:
    """Tokens the embedder sees for *text*, including [CLS] and [SEP]."""
    return len(_tokenizer().encode(text))


def _single_block(text: str, heading_path: str = "Section", anchor: str | None = None):
    return (text, (ExtractBlock(text, heading_path, anchor, 0, len(text)),))


def _blocks(*sections: tuple[str, str]) -> tuple[str, tuple[ExtractBlock, ...]]:
    """Build (full_text, blocks) the way extract.py does: bodies joined with blank lines."""
    blocks: list[ExtractBlock] = []
    offset = 0
    for heading_path, text in sections:
        if blocks:
            offset += 2
        blocks.append(ExtractBlock(text, heading_path, None, offset, offset + len(text)))
        offset += len(text)
    return "\n\n".join(text for _, text in sections), tuple(blocks)


def _assert_fits_model(full_text: str, chunks: list[Chunk]) -> None:
    for chunk in chunks:
        assert _model_tokens(chunk.text) <= EMBED_MAX_SEQ_LENGTH
        assert chunk.token_count <= MAX_CHUNK_TOKENS
        assert chunk.token_count == count_tokens(chunk.text)
        assert full_text[chunk.char_start : chunk.char_end] == chunk.text


# --------------------------------------------------------------------------- #
# Token counting
# --------------------------------------------------------------------------- #
def test_count_tokens_empty_string() -> None:
    assert count_tokens("") == 0


def test_count_tokens_uses_the_embedding_tokenizer() -> None:
    text = "Contact registrar@wlu.ca or call 519-884-1970 about CP104."
    assert count_tokens(text) == len(_tokenizer().encode(text, add_special_tokens=False))
    # The old words * 0.75 heuristic said 6 tokens for these 8 words.
    assert count_tokens(text) > len(text.split())


# --------------------------------------------------------------------------- #
# Model input limit
# --------------------------------------------------------------------------- #
def test_long_section_without_blank_lines_is_split_to_fit() -> None:
    full_text, blocks = _single_block((SENTENCE * 100).strip())  # ~3,000 words
    chunks = chunk_extracted_document(full_text, blocks)

    assert len(chunks) > 1
    _assert_fits_model(full_text, chunks)
    assert all(c.token_count <= TARGET_CHUNK_TOKENS for c in chunks)


def test_unbreakable_text_is_hard_cut_to_fit() -> None:
    full_text, blocks = _single_block("CP104/" * 1500)  # no whitespace, no sentence ends
    chunks = chunk_extracted_document(full_text, blocks)

    assert len(chunks) > 1
    _assert_fits_model(full_text, chunks)
    # No sentence breaks, so there is no overlap: the cuts must tile the source.
    assert chunks[0].char_start == 0
    assert chunks[-1].char_end == len(full_text)
    assert "".join(chunk.text for chunk in chunks) == full_text


def test_hard_cut_keeps_spaces_between_tokens() -> None:
    raw = ("tuition " * 800).strip()  # spaces, but no sentence punctuation to split on
    full_text, blocks = _single_block(raw)
    chunks = chunk_extracted_document(full_text, blocks)

    assert len(chunks) > 1
    _assert_fits_model(full_text, chunks)
    assert all(chunk.token_count <= TARGET_CHUNK_TOKENS for chunk in chunks)
    assert "".join(chunk.text for chunk in chunks) == full_text


def test_short_lines_cannot_exceed_the_model_limit() -> None:
    """Separators between pieces are tokens. Ignoring them used to pack one chunk
    past 512 on a page of one-word lines."""
    full_text, blocks = _single_block("\n".join(["deadline"] * 400))
    chunks = chunk_extracted_document(full_text, blocks)

    assert len(chunks) > 1
    _assert_fits_model(full_text, chunks)
    assert all(chunk.token_count <= TARGET_CHUNK_TOKENS for chunk in chunks)


def test_chunks_cover_the_whole_section() -> None:
    full_text, blocks = _single_block((SENTENCE * 60).strip())
    chunks = chunk_extracted_document(full_text, blocks)

    assert chunks[0].char_start == 0
    assert chunks[-1].char_end == len(full_text)
    for prev, nxt in itertools.pairwise(chunks):
        assert nxt.char_start <= prev.char_end  # contiguous or overlapping, never a gap


# --------------------------------------------------------------------------- #
# Overlap
# --------------------------------------------------------------------------- #
def test_overlap_is_capped_in_tokens_not_whole_paragraphs() -> None:
    paragraph = (SENTENCE * 10).strip()  # ~300 words
    full_text, blocks = _single_block("\n\n".join([paragraph] * 5))
    chunks = chunk_extracted_document(full_text, blocks)

    assert len(chunks) > 1
    _assert_fits_model(full_text, chunks)
    for prev, nxt in itertools.pairwise(chunks):
        overlap = full_text[nxt.char_start : prev.char_end]
        assert overlap, "consecutive chunks should share trailing context"
        assert count_tokens(overlap) <= OVERLAP_TOKENS
        assert overlap != paragraph


# --------------------------------------------------------------------------- #
# Short sections
# --------------------------------------------------------------------------- #
def test_short_deadline_section_is_kept() -> None:
    full_text, blocks = _single_block(DEADLINE, "Dates > Drop deadline", "drop")
    chunks = chunk_extracted_document(full_text, blocks)

    assert [c.text for c in chunks] == [DEADLINE]
    assert chunks[0].url_anchor == "drop"


def test_short_section_merges_into_sibling() -> None:
    fall = "Fall term classes begin in September and end in early December. " * 5
    full_text, blocks = _blocks(("Dates > Fall term", fall.strip()), ("Dates > Drop", DEADLINE))
    chunks = chunk_extracted_document(full_text, blocks)

    assert len(chunks) == 1
    assert DEADLINE in chunks[0].text
    assert chunks[0].heading_path == "Dates"
    _assert_fits_model(full_text, chunks)


def test_short_section_merges_with_parent_section() -> None:
    full_text, blocks = _blocks(
        ("Registrar", "Contact the Office of the Registrar."),
        ("Registrar > Hours", "Open 9 to 4, Monday to Friday."),
    )
    chunks = chunk_extracted_document(full_text, blocks)

    assert len(chunks) == 1
    assert chunks[0].heading_path == "Registrar"
    _assert_fits_model(full_text, chunks)


def test_short_sections_under_unrelated_headings_stay_separate() -> None:
    full_text, blocks = _blocks(
        ("Fees > Payment", "Pay by the 15th."), ("Housing > Move-in", DEADLINE)
    )
    chunks = chunk_extracted_document(full_text, blocks)

    assert [c.heading_path for c in chunks] == ["Fees > Payment", "Housing > Move-in"]


def test_unrelated_top_level_sections_are_not_merged() -> None:
    """Top-level headings have no parent. Treating "" as a shared parent used to
    merge Fees with Housing and replace both headings with an empty path."""
    full_text, blocks = _blocks(("Fees", "Pay by the 15th."), ("Housing", "Move in on Saturday."))
    chunks = chunk_extracted_document(full_text, blocks)

    assert [c.heading_path for c in chunks] == ["Fees", "Housing"]
    assert [c.text for c in chunks] == ["Pay by the 15th.", "Move in on Saturday."]
    _assert_fits_model(full_text, chunks)


def test_many_short_sibling_sections_stay_within_the_limit_and_are_kept() -> None:
    sections = tuple((f"Dates > Item {i}", f"Note {i}.") for i in range(120))
    full_text, blocks = _blocks(*sections)
    chunks = chunk_extracted_document(full_text, blocks)

    _assert_fits_model(full_text, chunks)
    assert all(chunk.token_count <= TARGET_CHUNK_TOKENS for chunk in chunks)
    for i in range(120):
        assert any(f"Note {i}." in chunk.text for chunk in chunks)


def test_short_section_next_to_a_large_one_is_not_dropped() -> None:
    full_text, blocks = _blocks(
        ("Dates > Policy", (SENTENCE * 30).strip()), ("Dates > Drop", DEADLINE)
    )
    chunks = chunk_extracted_document(full_text, blocks)

    assert any(DEADLINE in c.text for c in chunks)
    _assert_fits_model(full_text, chunks)


def test_only_empty_text_is_discarded() -> None:
    full_text, blocks = _blocks(("A", "   "), ("B", "a"))
    chunks = chunk_extracted_document(full_text, blocks)

    assert [c.text for c in chunks] == ["a"]


def test_chunk_empty_blocks() -> None:
    assert chunk_extracted_document("", ()) == []


# --------------------------------------------------------------------------- #
# Metadata
# --------------------------------------------------------------------------- #
def test_single_section_keeps_heading_and_anchor() -> None:
    text = "This is a medium-sized block of text. " * 20
    full_text, blocks = _single_block(text, "About", "about-section")
    chunks = chunk_extracted_document(full_text, blocks)

    assert len(chunks) == 1
    assert chunks[0].heading_path == "About"
    assert chunks[0].url_anchor == "about-section"
    assert chunks[0].text == text.strip()


def test_split_section_keeps_heading_and_anchor_on_every_chunk() -> None:
    full_text, blocks = _single_block((SENTENCE * 60).strip(), "Fees > Late Penalties", "late")
    chunks = chunk_extracted_document(full_text, blocks)

    assert len(chunks) > 1
    assert {c.heading_path for c in chunks} == {"Fees > Late Penalties"}
    assert {c.url_anchor for c in chunks} == {"late"}


def test_extracted_page_offsets_locate_chunks_in_full_text() -> None:
    html = (
        "<html><body><main>"
        "<h1 id='dates'>Important Dates</h1>"
        f"<p>{SENTENCE * 30}</p><p>{SENTENCE * 30}</p>"
        "<h2 id='drop'>Drop deadline</h2>"
        f"<p>{DEADLINE}</p>"
        "<h2 id='refunds'>Refunds</h2>"
        "<p>Refunds are issued within four weeks.</p>"
        "</main></body></html>"
    )
    doc = extract_document(
        url="https://students.wlu.ca/dates", content_type="text/html", body=html.encode()
    )
    assert doc is not None
    chunks = chunk_extracted_document(doc.full_text, doc.blocks)

    _assert_fits_model(doc.full_text, chunks)
    assert any(DEADLINE in c.text for c in chunks)


# --------------------------------------------------------------------------- #
# Chunk dataclass
# --------------------------------------------------------------------------- #
def test_chunk_dataclass_frozen() -> None:
    chunk = Chunk(
        text="test", heading_path="Test", char_start=0, char_end=4, url_anchor=None, token_count=1
    )
    with pytest.raises(AttributeError):
        chunk.text = "modified"  # type: ignore[misc]


def test_chunk_invalid_char_range() -> None:
    with pytest.raises(ValueError, match="char_start.*char_end"):
        Chunk(
            text="test",
            heading_path="Test",
            char_start=10,
            char_end=5,
            url_anchor=None,
            token_count=1,
        )


def test_chunk_negative_token_count() -> None:
    with pytest.raises(ValueError, match="token_count"):
        Chunk(
            text="test",
            heading_path="Test",
            char_start=0,
            char_end=4,
            url_anchor=None,
            token_count=-1,
        )
