# Ingest pipeline — Ingest pod

Turns Laurier's public web pages into an indexed, refreshable knowledge base.

`crawler.py` → `extract.py` → `chunk.py` → `embed.py` — wired together by `pipeline.py`

**Invariant you own: INV-1.** Only public Laurier pages enter the index. The hostname allowlist is `CRAWL_ALLOWLIST` in `app/core/config.py` (not a `*.wlu.ca` wildcard); `robots.txt` is respected without exception; the crawler identifies itself with a contact address.

**Embedding model:** BAAI/bge-base-en-v1.5 (768-dimensional). See ADR-006 in SDD §13 for selection rationale: zero cost, strong retrieval quality, CPU-friendly for nightly batch processing.

Spec: [SDD §5.1](../../../docs/SDD.md#51-ingest-pipeline) and [issue #6 (heading-aware chunker)](https://github.com/LaurierCS/locah-ai/issues/6)

## Orchestrator / CLI (`pipeline.py` + `run.py`)

Runs the full pipeline end-to-end against the live database.

```bash
cd backend
uv run alembic upgrade head          # apply schema migrations if needed
uv run python -m app.ingest.run      # run the full crawl → embed pipeline
uv run python -m app.ingest.run --force  # re-embed even unchanged pages
```

`DATABASE_URL` is read from the environment or from `backend/.env` / `.env` at
the repo root (via `app.core.config.settings`).

**What the summary output looks like:**

```
=== Ingest summary ===
  Pages fetched:      142
  Chunks upserted:    1834
  Skipped unchanged:  98
  Extract skipped:    4
  Errors:             0
```

- **Pages fetched** — pages where extraction/chunking/embedding was attempted.
- **Chunks upserted** — chunk rows written across newly-embedded pages.
- **Skipped unchanged** — pages skipped because `content_hash` matched `embedded_hash` (idempotency).
- **Extract skipped** — pages where extraction returned nothing (unsupported content-type or empty body).
- **Errors** — pages that raised an unhandled exception; the pipeline logged and continued.

**Partial failure:** any exception on a single page is caught, logged with a
full traceback, and counted in **Errors**.  The pipeline always finishes the
remaining pages.

**Idempotency:** re-running against unchanged pages produces zero re-embeds.
`embed_document` checks `documents.embedded_hash` (written by migration `003`)
against the current `documents.content_hash`; when they match it returns
`skipped=True` without calling the encoder.

**CLI note:** the current entry point is a minimal `asyncio`-based script.
If richer subcommands or `--help` output become a requirement, swap
`argparse` in `run.py` for [Typer](https://typer.tiangolo.com/) (add
`typer[all]` to `pyproject.toml` first).

### Key functions

| Function | Module | Purpose |
|----------|--------|---------|
| `run_ingest(session)` | `pipeline.py` | End-to-end: crawl → persist → extract → chunk → embed |
| `process_crawl_results(session, results)` | `pipeline.py` | Extract/chunk/embed a pre-crawled list |
| `format_ingest_summary(summary)` | `pipeline.py` | Human-readable summary string |
| `start_crawl_job()` | `jobs.py` | Runs `run_ingest` as a background job (one at a time); backs `POST /api/v1/admin/crawl` (see [API README](../api/README.md)) |

Both functions accept an optional `encoder=` argument so integration tests can
inject a mock model and run without a sentence-transformers download.

## Crawler (`crawler.py`)

Fetches allowlisted URLs and persists document metadata (`url`, `content_hash`, etc.).
Successful HTTP 200 responses retain **`CrawlResult.body`** (raw bytes) and
**`CrawlResult.content_type`** in memory so the orchestrator can pass them to
`extract_document`. Content is hashed from **`resp.content`** so PDFs stay binary-safe.

`crawl(session)` returns `list[CrawlResult]` so callers (the orchestrator, and
the admin endpoint #38) can continue processing without re-running the crawl.

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

## Embedder (`embed.py`)

Turns chunks into dense vectors and upserts them into `chunks.embedding` (`vector(768)`).

```python
from app.ingest.embed import embed_document

result = await embed_document(
    session,  # SQLAlchemy AsyncSession
    document_id=doc_id,  # documents.id the chunks belong to
    content_hash=doc.content_hash,  # current fingerprint of the page
    chunks=chunks,  # list[Chunk] from the chunker
)
# EmbedResult(document_id=..., embedded=<n>, skipped=<bool>)
```

**Model:** [BAAI/bge-base-en-v1.5](https://huggingface.co/BAAI/bge-base-en-v1.5) (768-dim), run locally on CPU via [sentence-transformers](https://www.sbert.net/) — zero API cost, no key. Read from `settings.embedding_model` (`EMBEDDING_MODEL`). Embeddings are normalized so pgvector cosine distance (the HNSW `vector_cosine_ops` index) behaves as expected. See ADR-006 in [SDD §13](../../../docs/SDD.md).

**Behaviour:**

1. **Skip unchanged.** Each document carries `embedded_hash` (migration `003`), the `content_hash` as of its last successful embed. When it equals the current `content_hash`, `embed_document` returns `skipped=True` and does no work. Pass `force=True` to re-embed regardless.
2. **Batched calls with backoff.** Text is embedded in batches (default 32); each batch retries on failure with exponential backoff (`backoff_base * 2**attempt`).
3. **Upsert + cleanup.** Chunk rows are upserted by `(document_id, ordinal)`; if a re-embed produces fewer chunks than before, now-excess rows are deleted. On success, `embedded_hash` is advanced to `content_hash` and the transaction is committed.

**Testing:** the embedding model is injectable (`encoder=`), so unit tests pass a mock and CI needs neither a model download nor a live database. See `tests/test_embedder.py`. The lower-level `embed_texts(texts, encoder=...)` exposes just the batching + backoff core.
