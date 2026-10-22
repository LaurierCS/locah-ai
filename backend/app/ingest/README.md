# Ingest pipeline — Ingest pod

Turns Laurier's public web pages into an indexed, searchable knowledge base.

**Invariant you own: INV-1.** Only public Laurier pages enter the index. The hostname allowlist is `CRAWL_ALLOWLIST` in `app/core/config.py`; `robots.txt` is respected without exception; the crawler identifies itself with a contact address.

**Embedding model:** BAAI/bge-base-en-v1.5 (768-dim), run locally on CPU via sentence-transformers — zero API cost, no key required. See ADR-006 in [SDD §13](../../../docs/SDD.md#13-architecture-decision-records).

Spec: [SDD §5.1](../../../docs/SDD.md#51-ingest-pipeline) and [issue #6](https://github.com/LaurierCS/locah-ai/issues/6).

---

## Pipeline overview

```mermaid
flowchart TB
  seedsYaml["seeds.yaml"]
  loadSeeds["seeds.py — load_seeds()"]
  crawlerState["crawler.py — CrawlerState"]
  urlPolicy["url_policy.py — is_crawlable_link()"]
  persist["persist_crawl_results() → documents table"]
  extract["extract.py — extract_document()"]
  quality["content_quality.py — is_usable_extracted_text()"]
  deactivate["deactivate_document() → mark inactive"]
  chunk["chunk.py — chunk_extracted_document()"]
  embed["embed.py — embed_document()"]
  skip["skip — content_hash unchanged"]
  pg[("Postgres — chunks + embedding")]
  summary["IngestSummary"]

  seedsYaml --> loadSeeds --> crawlerState
  crawlerState -->|"checks"| urlPolicy
  crawlerState --> persist
  persist --> extract
  extract -->|"None → extract_skipped++"| summary
  extract --> quality
  quality -->|"rejected → quality_rejected++"| deactivate --> summary
  quality -->|"pass"| chunk --> embed
  embed -->|"hash match"| skip -->|"skipped_unchanged++"| summary
  embed -->|"upsert"| pg -->|"chunks_upserted++"| summary
```

Each page is wrapped in its own try/except — one bad page never aborts the rest. Errors are logged and counted in `summary.errors`.

---

## Entry points

Three ways to run ingest:

```mermaid
flowchart LR
  CLI["uv run python -m app.ingest.run"]
  Admin["POST /api/v1/admin/crawl"]
  GHA["GitHub Actions crawl.yml"]

  CLI --> runPy["run.py → run_ingest()"]
  Admin --> jobs["jobs.start_crawl_job()"] --> runPy
  GHA --> Admin
```

```bash
cd backend
uv run alembic upgrade head            # apply schema if needed
uv run python -m app.ingest.run        # full crawl → embed
uv run python -m app.ingest.run --force  # re-embed even unchanged pages
```

`DATABASE_URL` is read from the environment or from `backend/.env` / `.env` at the repo root.

**Note on scope:** The GitHub Actions workflow sends `{"scope":"high_churn"}` or `{"scope":"full"}` in the request body, but the backend does not parse that field yet ([issue #100](https://github.com/LaurierCS/locah-ai/issues/100)). Both calls currently run a full `run_ingest()`. The schedule itself is real: nightly at 05:00 UTC for high-churn pages, full crawl every Sunday at 04:00 UTC.

**Ingest summary output:**

```
=== Ingest summary ===
  Pages fetched:      142
  Chunks upserted:    1834
  Skipped unchanged:  98
  Extract skipped:    4
  Quality rejected:   2
  Errors:             0
```

- **Pages fetched** — pages where extraction/chunking/embedding was attempted (status=success with a body).
- **Chunks upserted** — chunk rows written across newly-embedded pages.
- **Skipped unchanged** — pages where `content_hash` matched `embedded_hash` (idempotent re-runs).
- **Extract skipped** — pages where extraction returned nothing (unsupported content-type or empty body).
- **Quality rejected** — pages that passed extraction but were flagged as thin/boilerplate content.
- **Errors** — pages that raised an unhandled exception; pipeline logged the traceback and continued.

---

## Where ingest lands in Postgres

Ingest writes **`documents`** (one row per URL) and **`chunks`** (many rows per page, each with text + embedding).

```mermaid
erDiagram
  documents ||--o{ chunks : has

  documents {
    uuid id PK
    text url UK
    text title
    text content_hash
    text embedded_hash
    text etag
    int http_status
    text content_type
    timestamptz fetched_at
    boolean is_active
  }

  chunks {
    uuid id PK
    uuid document_id FK
    int ordinal
    text heading_path
    text chunk_text
    int token_count
    text url_anchor
    vector embedding
  }
```

Column meanings: **`documents.url`** — canonical page; **`content_hash`** — fingerprint of the latest fetched body; **`embedded_hash`** — `content_hash` at last successful embed (`NULL` if never embedded); **`is_active`** — `false` after quality rejection. **`chunks.ordinal`** — 0-based position on the page; **`chunks.chunk_text`** — stored as column `text` in SQL (shown here as `chunk_text` because `text` is awkward in Mermaid).

**Keys that matter:** `(document_id, ordinal)` is unique — re-embedding upserts by that pair and deletes higher ordinals if the page shrinks. **`content_hash`** changes whenever the crawler sees new bytes; **`embedded_hash`** records what was embedded last. When they match, `embed_document` skips the model ([migration `003`](../../migrations/versions/003_add_embedded_hash.py)).

---

## Files

### `seeds.yaml` + `seeds.py`

`seeds.yaml` is the hand-curated list of starting URLs grouped by topic (advising, academic calendar, co-op, registrar, wellness, etc.). `seeds.py` reads and validates it.

```mermaid
flowchart LR
  yaml["seeds.yaml — domain: [urls]"]
  loadSeeds["load_seeds()"]
  check{"hostname in\nCRAWL_ALLOWLIST?"}
  ok["return dict[domain, urls]"]
  fail["raise ValueError — fail fast"]

  yaml --> loadSeeds --> check
  check -->|yes| ok
  check -->|no| fail
```

`load_seeds()` raises `ValueError` immediately if any seed URL's hostname is not in `CRAWL_ALLOWLIST`. This catches misconfigured seeds at startup rather than silently crawling off-scope hosts.

**In plain terms:** `seeds.yaml` is the list of Laurier pages we intentionally start from; `seeds.py` loads that list and makes sure every URL is on an allowed host before the crawler runs.

---

### `url_policy.py`

Three pure predicates that decide what the crawler does with URLs. They live here — not in `crawler.py` — so they can be unit-tested without spinning up an HTTP client.

```mermaid
flowchart TD
  link["discovered link"]
  crawlCheck{"is_crawlable_link()"}
  schemeOk{"http/https?"}
  denyPath{"denylist path\nor extension?"}
  enqueue["enqueue for crawl"]
  drop["drop"]

  fetchDone["completed fetch"]
  errorCheck{"is_error_document_url()\nfinal URL?"}
  persistCheck{"is_persistable_fetch()"}
  writeDoc["write to documents"]
  skipDoc["skip persistence"]

  link --> crawlCheck --> schemeOk
  schemeOk -->|no| drop
  schemeOk -->|yes| denyPath
  denyPath -->|yes| drop
  denyPath -->|no| enqueue

  fetchDone --> errorCheck
  errorCheck -->|yes| skipDoc
  errorCheck -->|no| persistCheck
  persistCheck -->|yes| writeDoc
  persistCheck -->|no| skipDoc
```

- `is_crawlable_link` rejects asset files (`.css`, `.js`, images, fonts), infrastructure paths (`/_ato/`, `/dist/`, `/.well-known/`), and anything without an http(s) scheme.
- `is_error_document_url` catches Laurier's 404 helper pages by looking at the final URL after redirects (e.g. paths containing `/404/404.html` or query params like `req=`).
- `is_persistable_fetch` guards what actually gets written to `documents` — only real 200 responses with accepted content-types.

**In plain terms:** This file is the bouncer for URLs — it skips junk links like CSS and images, ignores Laurier’s “page not found” traps, and only saves fetches that are real content pages.

---

### `crawler.py`

The main crawler. `CrawlerState` manages the HTTP client, per-host queues, robots.txt caching, and the collected `CrawlResult` list. `crawl()` is the public entry point.

```mermaid
flowchart TB
  start["crawl — load seeds, group by host"]
  perHost["crawl_host — one host at a time"]
  robotsCheck["should_crawl_url — robots.txt, not already fetched"]
  fetchHash["fetch_and_hash — GET with If-None-Match"]
  status{"HTTP status"}
  s304["304 — skip, no body"]
  s200["200 — hash body, keep bytes in memory"]
  httpError["CrawlResult status error"]
  links["extract_links from HTML"]
  denylist{"is_crawlable_link?"}
  skipLink["skip link — debug log only"]
  enqueue["enqueue on host queue"]
  depthCap{"depth under cap?"}
  persist["persist_crawl_results → documents"]
  results["return list of CrawlResult"]

  start --> perHost --> robotsCheck
  robotsCheck -->|no| perHost
  robotsCheck -->|yes| fetchHash --> status
  status -->|304| s304 --> perHost
  status -->|200| s200 --> links
  status -->|other| httpError --> perHost
  links --> denylist
  denylist -->|no| skipLink
  denylist -->|yes| enqueue --> depthCap
  depthCap -->|yes| perHost
  s200 --> persist
  persist --> results
```

URLs on the queue were allowlisted when enqueued (seeds via `normalize_url`; discovered links only if they passed `is_crawlable_link`). The fetch loop does **not** call `is_crawlable_link` again before GET.

Key behaviours:
- Politeness: ≥ 1 s delay per host, one concurrent connection per host, descriptive `User-Agent` with a contact address.
- Etag caching: sends `If-None-Match` on revisit; a 304 means the page hasn't changed and the body is not reprocessed.
- Content is hashed from raw bytes so PDFs and HTML stay consistent with the stored hash.
- `CrawlResult.body` and `.content_type` are kept in memory so the orchestrator can pass them straight to `extract_document` without re-fetching.

**In plain terms:** The crawler walks Laurier’s site from the seed URLs, follows links within the rules, downloads each page (or skips it if unchanged), and records what it found so the next steps can read the page without hitting the web again.

---

### `extract.py`

Strips boilerplate and turns raw bytes into structured sections for the chunker.

```mermaid
flowchart LR
  input["body bytes + content_type"]
  dispatch{"content-type"}
  html["text/html → trafilatura markdown\n# headings, else HTML h tags"]
  pdf["application/pdf → pypdf\npage-by-page"]
  unsupported["log warning → return None"]
  out["ExtractedDocument"]

  input --> dispatch
  dispatch -->|html| html --> out
  dispatch -->|pdf| pdf --> out
  dispatch -->|other| unsupported
```

**`ExtractedDocument`** fields:

| Field | Meaning |
|-------|---------|
| `title` | Page title when available |
| `full_text` | All block text joined with blank lines |
| `blocks` | Tuple of `ExtractBlock` |

Each **`ExtractBlock`** carries:

| Field | Meaning |
|-------|---------|
| `text` | Section body (plain text) |
| `heading_path` | Breadcrumb, e.g. `Registrar > Fees`; `Page N` for PDF |
| `anchor_id` | HTML `id` on the source heading for `#fragment` citations; `None` for PDF |
| `char_start` / `char_end` | Character offsets in `full_text` (Python string indices) |

For HTML, trafilatura emits **markdown**; sections are split on `#` heading lines when present. If there are no markdown headings, the code falls back to `<h1>`–`<h6>` inside `<main>` / `<article>`. For PDF, pypdf reads page text and labels each block `Page {n}`.

**In plain terms:** Given raw HTML or PDF bytes, this step pulls out the actual article text — not the nav bar or footer — and tags each section with a heading trail so answers can point to the right part of the page.

---

### `content_quality.py`

Runs after extraction, before chunking. Decides whether the extracted text is worth keeping.

```mermaid
flowchart LR
  text["extracted full_text"]
  tokenCheck{"count_tokens(text)\n≥ 50?"}
  boilerCheck{"boilerplate\npatterns match?"}
  pass["pass → chunk + embed"]
  reject["reject → deactivate_document()"]

  text --> tokenCheck
  tokenCheck -->|no| reject
  tokenCheck -->|yes| boilerCheck
  boilerCheck -->|yes| reject
  boilerCheck -->|no| pass
```

- **Token floor (50 tokens ≈ 67 words):** catches navigation shells, empty redirect pages, and anything trafilatura technically extracted but that has no real prose.
- **Boilerplate fingerprints:** regex patterns for OneTrust cookie consent copy, privacy preference centres, and similar CMS-injected content that occasionally leaks through trafilatura's main-content extraction.
- Rejected pages: `deactivate_document()` marks the `documents` row `is_active=False` and deletes any existing `chunks` rows so the page never surfaces in search. The audit row stays.

**Known issue:** boilerplate regexes run on the **full** page text — a single cookie-banner phrase **anywhere** rejects the whole document ([issue #99](https://github.com/LaurierCS/locah-ai/issues/99)). Comments in code mention “near the start” but the implementation does not limit matches to a prefix.

**In plain terms:** After extraction, this step asks “is there enough real text here?” Pages that are mostly cookie banners or empty shells get pulled out of search so students don’t get junk hits.

---

### `chunk.py`

Splits an `ExtractedDocument` into overlapping, citation-ready segments.

**Strategy (as implemented today):**

1. Each `ExtractBlock` from extract keeps one `heading_path`; chunking splits **within** a block on `\n\n` paragraphs (blocks already align with sections).
2. Target ~800 **heuristic** tokens per chunk (`count_tokens` ≈ `words * 0.75`).
3. Overlap between consecutive chunks is **paragraph-based**, aiming near 120 heuristic tokens but often **one or more full paragraphs** (can exceed 120 in real tokens).
4. Drop chunks smaller than 50 heuristic tokens.

**`Chunk`** fields:

| Field | Meaning |
|-------|---------|
| `text` | Plain text content |
| `heading_path` | Breadcrumb from its `ExtractBlock` |
| `char_start` / `char_end` | Offsets in `full_text` (currently section-level in code, not per-chunk precise) |
| `url_anchor` | HTML anchor id for `#fragment` deep-links in citations |
| `token_count` | Heuristic from `count_tokens` — not the bge or Claude tokenizer |

**Known issues:** the heuristic **undercounts** real tokens (chunks can be much longer than 800 in bge’s 512-token window). Overlap and sizing need work for the embedding model — track in [issue #97](https://github.com/LaurierCS/locah-ai/issues/97). Heading/title context in vectors is [issue #98](https://github.com/LaurierCS/locah-ai/issues/98).

**In plain terms:** Long pages get cut into bite-sized passages with a bit of overlap, each tied to a heading, so search can return a specific paragraph instead of an entire 20-page PDF.

---

### `embed.py`

Turns chunk text into dense vectors and upserts them into `chunks.embedding`. The **embedding model** only runs in the encode step below — not during crawl, extract, or chunk. At ingest time, each chunk’s `text` is passed through [BAAI/bge-base-en-v1.5](https://huggingface.co/BAAI/bge-base-en-v1.5) via `sentence-transformers` (`settings.embedding_model`). The model outputs a **768-dimensional, L2-normalized** vector per chunk. Those vectors are what retrieval will compare to a question embedding later (pgvector cosine / HNSW). Hash checks and SQL upserts happen around the model; they do not call the model.

```mermaid
flowchart TB
  embedEntry["embed_document entry"]
  hashCheck{"embedded_hash matches content_hash?"}
  skipResult["Return skipped — model not loaded"]
  embedTexts["embed_texts — batch and retry wrapper"]
  batches["Split texts into batches of 32"]
  encodeStep["SentenceTransformer encode — bge-base-en-v1.5"]
  retryGate{"Batch failed?"}
  backoff["Exponential backoff then retry"]
  upsert["Upsert chunk rows with embedding column"]
  deleteStale["Delete stale ordinals if chunk count shrank"]
  updateHash["Set documents.embedded_hash"]
  embedDone["Return embedded chunk count"]

  embedEntry --> hashCheck
  hashCheck -->|yes| skipResult
  hashCheck -->|no| embedTexts --> batches --> encodeStep
  encodeStep --> retryGate
  retryGate -->|yes under max retries| backoff --> encodeStep
  retryGate -->|no| upsert --> deleteStale --> updateHash --> embedDone
```

- **Where the model runs:** `embed_texts` calls the cached `SentenceTransformer` encoder (or a test `encoder=` mock). `embed_document` only orchestrates DB reads/writes and invokes `embed_texts` when the page content hash changed.
- **Idempotency:** `embedded_hash` (migration `003`) stores the last successfully embedded `content_hash`. A match skips encode entirely — no model load, no vectors computed.
- **Batching + retry:** batches of 32; up to 4 retries with exponential backoff per failed batch.
- **Upsert + cleanup:** rows keyed by `document_id` + `ordinal`; extra ordinals from a previous run are deleted. Vectors are written as pgvector literals on the `embedding` column.
- **`Encoder` injection:** pass `encoder=` into `embed_document` / `embed_texts` in tests so CI never downloads the Hugging Face weights.

**In plain terms:** Each chunk’s words are turned into a numeric fingerprint the database can compare to future questions. If the page hasn’t changed since last time, this step skips the model entirely and leaves the old vectors in place.

---

### `pipeline.py`

The orchestrator. Wires `crawl()` → `extract_document()` → `is_usable_extracted_text()` → `chunk_extracted_document()` → `embed_document()` in a single pass with per-document error handling.

| Function | Purpose |
|----------|---------|
| `run_ingest(session)` | Full end-to-end: crawl seeds, persist document rows, then process |
| `process_crawl_results(session, results)` | Extract/chunk/embed a pre-crawled list; useful when you already have `CrawlResult`s |
| `IngestSummary` | Dataclass counting pages, chunks, skips, rejections, and errors |
| `format_ingest_summary(summary)` | Human-readable multi-line string for CLI and log output |

Both `run_ingest` and `process_crawl_results` accept `encoder=` for test injection and `force=True` to bypass the hash check.

**In plain terms:** This is the conductor — it runs crawl, then extract, quality check, chunk, and embed in order for every page, counts what happened, and keeps going even when one URL blows up.

---

### `run.py`

CLI entry point. Parses `--force`, creates an async engine, calls `run_ingest()`, and prints the summary to stdout. Logs go to stderr.

See the [Entry points](#entry-points) section above for usage.

**In plain terms:** When you run ingest from your laptop, this script is what you invoke — it connects to the database, runs the full pipeline once, and prints the summary at the end.

---

### `jobs.py`

Background job state for the `POST /api/v1/admin/crawl` endpoint. Tracks one in-process job at a time — a second request while one is running returns 409 immediately. A job moves `running` → `succeeded` when `run_ingest()` finishes, or `running` → `failed` on an unhandled exception.

`CrawlJob` is a plain dataclass (`job_id`, `status`, `started_at`, `finished_at`, `summary`, `error`). State is in-process — it resets on server restart. This assumes a single API worker, which holds for the current single-instance deployment.

**In plain terms:** When cron or an admin hits the crawl API, this file kicks off ingest in the background and remembers whether that job is still running, finished OK, or failed — without blocking the HTTP response.

---

## Cross-references

- [SDD §5.1](../../../docs/SDD.md#51-ingest-pipeline) — component spec
- [SDD §3 INV-1](../../../docs/SDD.md#3-invariants) — public-pages-only invariant
- [`backend/README.md`](../../README.md) — backend-wide setup and test commands
- [`backend/app/api/README.md`](../api/README.md) — admin endpoint details
