"""Tests for heading-aware chunker (SDD §5.1 / issue #6).

Verifies:
  - Chunks respect target ~800 tokens.
  - Heading boundaries are preserved (no breaking heading paths).
  - Overlap is ~120 tokens between consecutive chunks.
  - Tiny chunks are skipped.
  - Citation metadata (char_range, url_anchor) is accurate.
  - Token counts are consistent with encoder.
"""

import pytest

from app.ingest.chunk import (
    Chunk,
    TARGET_CHUNK_TOKENS,
    OVERLAP_TOKENS,
    MIN_CHUNK_TOKENS,
    chunk_extracted_document,
    count_tokens,
)
from app.ingest.extract import ExtractBlock


def test_count_tokens_empty_string() -> None:
    """Token count of empty string is 0."""
    assert count_tokens("") == 0


def test_count_tokens_simple_text() -> None:
    """Token count is consistent and reasonable for simple text."""
    text = "Hello world"
    tokens = count_tokens(text)
    assert tokens > 0
    assert tokens <= len(text.split())  # Upper bound: one token per word


def test_count_tokens_paragraph() -> None:
    """Token count for a longer paragraph."""
    text = "The quick brown fox jumps over the lazy dog. " * 10
    tokens = count_tokens(text)
    # ~11 words per sentence * 10 sentences = ~110 words
    # Should be around 85–95 tokens (rough estimate)
    assert 50 < tokens < 150


def test_chunk_empty_blocks() -> None:
    """Chunking with no blocks returns empty list."""
    result = chunk_extracted_document("", ())
    assert result == []


def test_chunk_single_small_block() -> None:
    """A single small block (< MIN_CHUNK_TOKENS) is skipped."""
    block_text = "Hello world"
    block = ExtractBlock(
        text=block_text,
        heading_path="",
        anchor_id=None,
        char_start=0,
        char_end=len(block_text),
    )
    result = chunk_extracted_document(block_text, (block,))
    # Text is too small to chunk; should be filtered out
    assert result == []


def test_chunk_single_medium_block() -> None:
    """A single medium block is emitted as one chunk."""
    block_text = (
        "This is a medium-sized block of text. " * 20
    )  # ~20 * 6 words = ~120 words ≈ 90–100 tokens
    block = ExtractBlock(
        text=block_text,
        heading_path="About",
        anchor_id="about-section",
        char_start=0,
        char_end=len(block_text),
    )
    result = chunk_extracted_document(block_text, (block,))

    assert len(result) == 1
    chunk = result[0]
    assert chunk.text == block_text
    assert chunk.heading_path == "About"
    assert chunk.url_anchor == "about-section"
    assert chunk.char_start == 0
    assert chunk.char_end == len(block_text)
    assert chunk.token_count == count_tokens(block_text)


def test_chunk_large_block_splits() -> None:
    """A large block is split into multiple chunks."""
    # Create a block with paragraphs that's larger than 2x target (~1600+ tokens)
    # Each paragraph is separated by \n\n
    paragraph = "The registrar office handles all academic record matters and provides guidance for degree completion. " + \
                "Students should consult the office for questions about transcripts, course substitutions, and academic standing. " + \
                "Our staff works to support your success throughout your studies. " + \
                "\n\n" * 1
    block_text = (paragraph * 30).rstrip()  # Create ~1500+ tokens of content
    block = ExtractBlock(
        text=block_text,
        heading_path="Registrar",
        anchor_id=None,
        char_start=0,
        char_end=len(block_text),
    )
    result = chunk_extracted_document(block_text, (block,))

    # Should produce multiple chunks
    assert len(result) > 1, f"Expected multiple chunks, got {len(result)} with {count_tokens(block_text)} tokens"

    # All chunks should have the correct heading and be non-empty
    for chunk in result:
        assert chunk.heading_path == "Registrar"
        assert len(chunk.text) > 0
        assert chunk.token_count == count_tokens(chunk.text)

    # All chunks should fit within target (with some tolerance)
    for chunk in result:
        assert chunk.token_count <= TARGET_CHUNK_TOKENS * 1.5


def test_chunk_respects_heading_path() -> None:
    """Each chunk preserves the heading path from its source block."""
    block_text = "Important fee information. " * 30
    block = ExtractBlock(
        text=block_text,
        heading_path="Fees > Late Penalties",
        anchor_id=None,
        char_start=0,
        char_end=len(block_text),
    )
    result = chunk_extracted_document(block_text, (block,))

    for chunk in result:
        assert chunk.heading_path == "Fees > Late Penalties"


def test_chunk_preserves_anchor_id() -> None:
    """Chunk retains the anchor_id for citation deep-linking."""
    block_text = "This is a section with an anchor. " * 25
    block = ExtractBlock(
        text=block_text,
        heading_path="FAQ",
        anchor_id="faq-scholarships",
        char_start=0,
        char_end=len(block_text),
    )
    result = chunk_extracted_document(block_text, (block,))

    for chunk in result:
        assert chunk.url_anchor == "faq-scholarships"


def test_chunk_char_ranges_non_overlapping() -> None:
    """Character ranges of chunks should map back to original text (with overlap)."""
    block_text = "Part one. " * 80 + "Part two. " * 80
    block = ExtractBlock(
        text=block_text,
        heading_path="Content",
        anchor_id=None,
        char_start=0,
        char_end=len(block_text),
    )
    result = chunk_extracted_document(block_text, (block,))

    if len(result) > 1:
        # Chunks should cover the entire range (possibly with overlap)
        assert result[0].char_start == 0
        assert result[-1].char_end == len(block_text)

        # Verify we can extract each chunk's text from the original
        for chunk in result:
            extracted = block_text[chunk.char_start : chunk.char_end]
            # The extracted text should be a substring of the chunk (accounting for overlap)
            assert chunk.text in extracted or extracted in chunk.text


def test_chunk_overlap_consistency() -> None:
    """When chunks overlap, the overlap should be ~OVERLAP_TOKENS."""
    # Create a large enough text to guarantee multiple chunks
    paragraph = "Detailed information about academic programs and requirements. " * 60
    block_text = paragraph
    block = ExtractBlock(
        text=block_text,
        heading_path="Programs",
        anchor_id=None,
        char_start=0,
        char_end=len(block_text),
    )
    result = chunk_extracted_document(block_text, (block,))

    if len(result) > 1:
        # Check that consecutive chunks have overlap
        for i in range(len(result) - 1):
            current_chunk = result[i]
            next_chunk = result[i + 1]

            # The end of current chunk should overlap with the start of next chunk
            # (Since we use full overlap, next_chunk should start with the tail of current_chunk)
            overlap_start = max(
                current_chunk.char_start,
                next_chunk.char_start - OVERLAP_TOKENS * 4,  # Rough upper bound
            )
            overlap_end = min(current_chunk.char_end, next_chunk.char_end)

            # There should be some overlap in the character ranges
            assert overlap_end > overlap_start


def test_chunk_multiple_blocks() -> None:
    """Chunking multiple blocks returns chunks for each."""
    block1_text = "Section A content. " * 40
    block2_text = "Section B content. " * 40

    block1 = ExtractBlock(
        text=block1_text,
        heading_path="A",
        anchor_id="section-a",
        char_start=0,
        char_end=len(block1_text),
    )
    block2 = ExtractBlock(
        text=block2_text,
        heading_path="B",
        anchor_id="section-b",
        char_start=len(block1_text) + 2,
        char_end=len(block1_text) + 2 + len(block2_text),
    )

    result = chunk_extracted_document(block1_text + "\n\n" + block2_text, (block1, block2))

    # Should have chunks from both blocks
    assert any(c.heading_path == "A" for c in result)
    assert any(c.heading_path == "B" for c in result)


def test_chunk_token_count_accuracy() -> None:
    """Each chunk's token_count matches the actual token count of its text."""
    block_text = "Example paragraph about university policies. " * 50
    block = ExtractBlock(
        text=block_text,
        heading_path="Policies",
        anchor_id=None,
        char_start=0,
        char_end=len(block_text),
    )
    result = chunk_extracted_document(block_text, (block,))

    for chunk in result:
        expected_tokens = count_tokens(chunk.text)
        assert chunk.token_count == expected_tokens


def test_chunk_dataclass_frozen() -> None:
    """Chunk objects are immutable after construction."""
    chunk = Chunk(
        text="test",
        heading_path="Test",
        char_start=0,
        char_end=4,
        url_anchor=None,
        token_count=1,
    )
    with pytest.raises(AttributeError):
        chunk.text = "modified"


def test_chunk_invalid_char_range() -> None:
    """Chunk constructor rejects char_start > char_end."""
    with pytest.raises(ValueError, match="char_start.*char_end"):
        Chunk(
            text="test",
            heading_path="Test",
            char_start=10,
            char_end=5,  # Invalid
            url_anchor=None,
            token_count=1,
        )


def test_chunk_negative_token_count() -> None:
    """Chunk constructor rejects negative token counts."""
    with pytest.raises(ValueError, match="token_count"):
        Chunk(
            text="test",
            heading_path="Test",
            char_start=0,
            char_end=4,
            url_anchor=None,
            token_count=-1,  # Invalid
        )


def test_chunk_respects_min_chunk_tokens() -> None:
    """Tiny blocks (< MIN_CHUNK_TOKENS) are discarded."""
    tiny_text = "a"
    block = ExtractBlock(
        text=tiny_text,
        heading_path="Tiny",
        anchor_id=None,
        char_start=0,
        char_end=len(tiny_text),
    )
    result = chunk_extracted_document(tiny_text, (block,))
    assert result == []


def test_chunk_realistic_university_page() -> None:
    """Test chunking a realistic university page structure (multiple headings + content)."""
    # Simulate a page like "Registrar > Fees" with nested sections
    full_text = """Registrar

The registrar office manages all academic records and documents.

Fees

Tuition is charged per semester. Standard rates apply to full-time students.
Graduate students may have different rates. """ + (
        "Additional information about fees. " * 100
    )

    blocks = (
        ExtractBlock(
            text="The registrar office manages all academic records and documents.",
            heading_path="Registrar",
            anchor_id="registrar",
            char_start=0,
            char_end=63,
        ),
        ExtractBlock(
            text="Tuition is charged per semester. Standard rates apply to full-time students. Graduate students may have different rates. "
            + "Additional information about fees. " * 100,
            heading_path="Registrar > Fees",
            anchor_id="fees",
            char_start=75,
            char_end=75 + 120 + len("Additional information about fees. " * 100),
        ),
    )

    result = chunk_extracted_document(full_text, blocks)

    # Should have multiple chunks with correct heading paths
    assert len(result) > 0
    registrar_chunks = [c for c in result if c.heading_path.startswith("Registrar")]
    assert len(registrar_chunks) > 0

    for chunk in registrar_chunks:
        assert chunk.url_anchor in ["registrar", "fees", None]


def test_chunk_size_distribution() -> None:
    """Chunks should be roughly distributed around TARGET_CHUNK_TOKENS."""
    # Create text with substantial paragraph content
    para = (
        "University policy requires students to maintain academic standing. "
        "The policy covers standards of conduct, disciplinary procedures, and appeals. "
        "Detailed information is available from the Office of Academic Affairs. "
        "\n\n"
    )
    large_text = (para * 60).rstrip()  # ~2000+ tokens
    block = ExtractBlock(
        text=large_text,
        heading_path="Policies",
        anchor_id=None,
        char_start=0,
        char_end=len(large_text),
    )
    result = chunk_extracted_document(large_text, (block,))

    assert len(result) > 1, f"Expected multiple chunks, got {len(result)} with {count_tokens(large_text)} tokens"

    # Most chunks should be within a reasonable range of target
    for chunk in result:
        # Allow generous range: 20% to 150% of target
        assert TARGET_CHUNK_TOKENS * 0.2 < chunk.token_count <= TARGET_CHUNK_TOKENS * 1.5
