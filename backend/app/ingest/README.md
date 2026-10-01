# Ingest pipeline — Ingest pod

Turns Laurier's public web pages into an indexed, refreshable knowledge base.

`crawler.py` → `extract.py` → `chunk.py` → `embed.py`

**Invariant you own: INV-1.** Only public Laurier pages enter the index. The hostname allowlist is `CRAWL_ALLOWLIST` in `app/core/config.py` (not a `*.wlu.ca` wildcard); `robots.txt` is respected without exception; the crawler identifies itself with a contact address.

**Embedding model:** BAAI/bge-base-en-v1.5 (768-dimensional). See ADR-006 in SDD §13 for selection rationale: zero cost, strong retrieval quality, CPU-friendly for nightly batch processing.

Spec: [SDD §5.1](../../../docs/SDD.md#51-ingest-pipeline) and [issue #6 (heading-aware chunker)](https://github.com/LaurierCS/locah-ai/issues/6)

## Crawler (`crawler.py`)

Fetches allowlisted URLs and persists document metadata (`url`, `content_hash`, etc.). Successful HTTP 200 responses also retain **`CrawlResult.body`** (raw bytes) and **`CrawlResult.content_type`** in memory for the extract step; the orchestrator (#37) will pass these to `extract_document`. Content is hashed from **`resp.content`** so PDFs stay binary-safe.

## Extractor (`extract.py`)

Strips boilerplate and turns raw bodies into structured sections for the chunker.

```python
from app.ingest.extract import extract_document

doc = extract_document(url=..., content_type=..., body=crawl_result.body)
```

**Returns** `ExtractedDocument | None`:

| Field | Meaning |
|-------|---------|
| `title` | Page title when available |
| `full_text` | All block text joined with blank lines |
| `blocks` | Tuple of `ExtractBlock` |

Each **`ExtractBlock`** has:

- **`text`** — section body (plain text)
- **`heading_path`** — breadcrumb with ` > ` between levels (e.g. `Registrar > Fees`), or `Page N` for PDF pages
- **`anchor_id`** — HTML `id` on the source heading when present (for `#fragment` citations); `None` for PDF
- **`char_start` / `char_end`** — offsets in `full_text` (maps to SDD `char_range`)

**HTML:** [trafilatura](https://github.com/adbar/trafilatura) for main content; heading structure from markdown `#` lines when present, otherwise from `<h1>`–`<h6>` inside `<main>` / `<article>`.

**PDF:** [pypdf](https://pypi.org/project/pypdf/) per-page text; each block is labeled `Page {n}` in both `heading_path` and the block text prefix.

Unsupported or empty extraction logs a warning and returns `None`.

## Chunker (`chunk.py`)

Splits extracted documents into overlapping, citation-ready segments with heading boundaries.

```python
from app.ingest.chunk import chunk_extracted_document

chunks = chunk_extracted_document(doc.full_text, doc.blocks)
```

**Inputs:**
- `doc.full_text` — Concatenated text from all blocks (from `ExtractedDocument`)
- `doc.blocks` — Tuple of `ExtractBlock` objects with heading paths and anchors

**Returns** `list[Chunk]`:

| Field | Meaning |
|-------|---------|
| `text` | Plain text content of the chunk |
| `heading_path` | Breadcrumb hierarchy (e.g., `Registrar > Fees`) |
| `char_start` / `char_end` | Character offsets in full document (maps to `SDD char_range`) |
| `url_anchor` | HTML anchor id for deep-linking `#fragments` in citations |
| `token_count` | Approximate token count (heuristic: `words * 0.75`) |

**Chunking strategy:**

1. **Heading boundaries first:** Each chunk preserves heading context; no breaking `heading_path` mid-chunk.
2. **Recursive split:** Target ~800 tokens per chunk; split on `\n\n` paragraph boundaries to avoid breaking sentences.
3. **120-token overlap:** Consecutive chunks overlap by ~120 tokens to maintain retrieval context (enables sliding-window retrieval).
4. **No tiny chunks:** Chunks smaller than 50 tokens are skipped to avoid fragmentation.

**Token counting:** Uses a language-agnostic heuristic (`words * 0.75`) that approximates the Claude model encoder. When the embedding model is finalized (S2–S3), upgrade to `anthropic.Anthropic().messages.count_tokens(...)` for exact counts.

**Invariants:**
- Every chunk's `token_count` matches the actual count of its `text`.
- `char_start` and `char_end` are valid offsets into `doc.full_text`.
- When retrieved for citations, a chunk's `text` contains the quoted passage and `url_anchor` points to the right section.
