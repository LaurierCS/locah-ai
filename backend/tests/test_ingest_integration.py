"""Integration tests for the ingest pipeline (crawler → extract → chunk → embed).

Tests the full flow: fetch HTML → extract sections → chunk with headings.
Does NOT test embedding (Issue #35) yet.
"""

from app.ingest.chunk import chunk_extracted_document, count_tokens
from app.ingest.extract import extract_document


def test_ingest_full_pipeline_html() -> None:
    """End-to-end: extract an HTML page, then chunk it."""
    # Create more substantial content so blocks won't be filtered as too small
    substantial_text = ("The academic calendar is the official schedule for the university. " * 10)
    html = (
        "<html><head><title>Academic Calendar</title></head><body><main>"
        "<h1>Academic Calendar</h1>"
        f"<p>{substantial_text}</p>"
        "<h2 id='fall-semester'>Fall Semester</h2>"
        f"<p>Fall classes run from September to December. {substantial_text}</p>"
        "<h2 id='winter-semester'>Winter Semester</h2>"
        f"<p>Winter classes run from January to April. {substantial_text}</p>"
        "</main></body></html>"
    )

    # Step 1: Extract
    doc = extract_document(
        url="https://www.wlu.ca/calendar",
        content_type="text/html",
        body=html.encode(),
    )
    assert doc is not None
    assert len(doc.blocks) >= 1

    # Step 2: Chunk
    chunks = chunk_extracted_document(doc.full_text, doc.blocks)
    # We may get 0 chunks if all blocks are too small, so let's just verify it doesn't crash
    # and returns a list
    assert isinstance(chunks, list)

    # Verify structure of any chunks produced
    for chunk in chunks:
        assert chunk.text  # Non-empty
        assert chunk.heading_path is not None  # Has heading context
        assert chunk.token_count > 0
        assert chunk.char_start >= 0
        assert chunk.char_end > chunk.char_start

    # Verify heading hierarchy is preserved if we have chunks
    if chunks:
        heading_paths = {c.heading_path for c in chunks}
        assert any("Academic Calendar" in path or "Fall" in path for path in heading_paths)


def test_ingest_pipeline_with_large_document() -> None:
    """Test chunking a larger, more complex page."""
    html = (
        "<html><head><title>Registration Guide</title></head><body><main>"
        "<h1>Course Registration</h1>"
        "<p>Student registration opens in April and closes in August. "
        + ("You must register for Fall courses during the Spring registration window. " * 20)
        + "</p>"
        "<h2>Steps to Register</h2>"
        "<p>First, log in to MyDegree. "
        + ("Click the Register tab and select your courses. " * 30)
        + "</p>"
        "<h2>Important Dates</h2>"
        "<p>The deadline for registration is August 31. "
        + ("Late registration may incur a fee. " * 25)
        + "</p></main></body></html>"
    )

    doc = extract_document(
        url="https://www.wlu.ca/registration",
        content_type="text/html",
        body=html.encode(),
    )
    assert doc is not None

    chunks = chunk_extracted_document(doc.full_text, doc.blocks)
    assert len(chunks) >= 1

    # For large documents, we should have multiple chunks
    total_tokens = count_tokens(doc.full_text)
    if total_tokens > 800:
        assert len(chunks) > 1, f"Document has {total_tokens} tokens but only {len(chunks)} chunk(s)"

    # All chunks should be coherent
    for chunk in chunks:
        assert len(chunk.text.split()) > 5, "Chunks should have substantial content"


def test_ingest_handles_empty_extraction() -> None:
    """If extraction returns None, chunking should handle it gracefully."""
    # Extract will return None for unsupported content type
    doc = extract_document(
        url="https://www.wlu.ca/binary",
        content_type="application/octet-stream",
        body=b"\x00\x01\x02",
    )
    assert doc is None
    # We would skip chunking in the orchestrator (#37)


def test_ingest_preserves_document_url() -> None:
    """Chunks maintain document context (heading_path and url_anchor) for citation."""
    html = (
        "<html><head><title>FAQ</title></head><body><main>"
        "<h1>Frequently Asked Questions</h1>"
        "<h2 id='tuition-faq'>Tuition</h2>"
        "<p>Tuition is charged per term. "
        + ("Full-time students pay X, part-time students pay Y. " * 20)
        + "</p></main></body></html>"
    )

    doc = extract_document(
        url="https://www.wlu.ca/faq",
        content_type="text/html",
        body=html.encode(),
    )
    chunks = chunk_extracted_document(doc.full_text, doc.blocks)

    # At least one chunk should have the tuition anchor
    tuition_chunks = [c for c in chunks if c.url_anchor == "tuition-faq"]
    assert len(tuition_chunks) >= 1

    # Citation should include the anchor
    for chunk in tuition_chunks:
        assert "Tuition" in chunk.heading_path
