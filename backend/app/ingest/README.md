# Ingest pipeline — Ingest pod

Turns Laurier's public web pages into an indexed, refreshable knowledge base.

`crawler.py` → `extract.py` → `chunk.py` → `embed.py`

**Invariant you own: INV-1.** Only public Laurier pages enter the index. The hostname allowlist is `CRAWL_ALLOWLIST` in `app/core/config.py` (not a `*.wlu.ca` wildcard); `robots.txt` is respected without exception; the crawler identifies itself with a contact address.

Embedding model is TBD in S1. Schema is `vector(1024)` until then.

Spec: [SDD §5.1](../../../docs/SDD.md#51-ingest-pipeline)

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
