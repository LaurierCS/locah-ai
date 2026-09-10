# LOCAH.ai — Software Design Document

**Laurier Online Course Agent Helper**
Owner: Laurier Computing Society
Status: Draft v0.1 — Semester 1 (MVP)
Last updated: 2026-09-10

---

## 0. How to read this document

This SDD is the engineering contract for Semester 1. It describes **what we are building, how it is structured, and what "done" means**. It deliberately specifies the *seams* (module boundaries, data contracts, interfaces) tightly and leaves implementation detail inside each module to the engineer who owns it.

Anything marked **[PHASE 2]** is out of scope for Semester 1 and is documented only so that Semester 1 decisions do not block it.

Non-negotiable constraints are marked **[INVARIANT]**. These come from the funding proposal's privacy commitments to the Students' Union. An implementation that violates an invariant is a bug, regardless of how well it performs.

---

## 1. Problem statement

Laurier's public information is accurate but fragmented:

- Nine separate advising teams with no single entry point; a student's first task is figuring out which team they belong to.
- Degree progression is split across three systems (MyDegree, Academic Calendar, important-dates page).
- Co-op spans ~8–10 subpages, and the two most-needed facts (GPA threshold, application deadline) appear on none of them.
- Advisors absorb the overflow one message at a time, with no mechanism that converts forty identical questions into one fixed web page.

**LOCAH.ai** is a retrieval-augmented assistant over Laurier's *public* web presence that (a) answers student questions with citations, (b) surfaces support services a student didn't know existed, and (c) aggregates what students ask into a prioritized list of what Laurier should fix at the source.

---

## 2. Scope

### 2.1 In scope — Semester 1 MVP

| # | Capability | Description |
|---|---|---|
| F1 | Crawler & knowledge base | Politely crawl `*.wlu.ca` public pages, extract main content, chunk, embed, index. Scheduled refresh. |
| F2 | Cited question answering | Retrieve → generate → every factual claim carries a source URL. Refuse rather than guess when retrieval is weak. |
| F3 | Conflict surfacing | When two retrieved sources disagree on the same fact, present both with their URLs instead of picking one. |
| F4 | Support-resource surfacing | When a question touches wellbeing, accessibility, financial aid, or advising, surface the relevant published Laurier resource alongside the answer. |
| F5 | Question analytics + trends dashboard | De-identified logging of question text, weekly clustering, ranked "most asked / worst answered" report with k-anonymity suppression. |
| F6 | Evaluation harness | A gold-set of ~150 questions with known answers; automated scoring of correctness, citation validity, and refusal behaviour. Gates every release. |

### 2.2 Explicitly out of scope — Semester 1

- **[PHASE 2]** Advisor triage tool (classification, draft replies, urgency escalation).
- **[PHASE 3]** MyDegree audit parsing and personalised degree guidance. Requires ICT sponsorship, SAML 2.0/OIDC SSO, and a formal privacy review. Not requested in the funding proposal.
- Any authenticated student data of any kind.
- Any autonomous outbound communication to students.
- Native mobile apps.

### 2.3 Non-goals (permanent)

LOCAH.ai does not screen, diagnose, counsel, or generate wellbeing advice of its own. It surfaces resources Laurier already publishes and connects students to people.

---

## 3. Invariants

These are enforced in code and verified by tests. Each has an owning test file.

| ID | Invariant | Enforcement |
|---|---|---|
| **INV-1** | The knowledge base contains **public web pages only**. No student records, internal systems, or proprietary documents. | Crawler domain+robots allowlist; ingestion rejects any non-HTTP source. `tests/test_crawler_scope.py` |
| **INV-2** | **No PII reaches the model provider.** Names, student numbers, emails, phone numbers are stripped and replaced with placeholders before any outbound LLM call; placeholders restored locally. | `app/core/redaction.py` sits on the only egress path. `tests/test_redaction.py` |
| **INV-3** | **Raw question text is never persisted with identity.** Analytics stores a redacted question, a topic label, and a timestamp. No IP, no session-to-person linkage, no account. | `app/analytics/logging.py`; DB schema has no user table in MVP. `tests/test_analytics_schema.py` |
| **INV-4** | **Every factual sentence carries a citation**, and every citation resolves to a URL actually present in the retrieved context. | Post-generation citation validator rejects unsupported claims. `tests/test_citation_validation.py` |
| **INV-5** | **Distress signals escalate, never de-prioritize.** A wellbeing signal can only add a human-facing resource and a "talk to a person" path. It can never suppress, rank down, or auto-resolve. | `app/core/safety.py` — one-way gate, no downward path exists. `tests/test_safety_gate.py` |
| **INV-6** | **Aggregate reports suppress small counts.** No category is reported below k=5 students. Wellbeing categories at coarsest useful grain. | `app/analytics/report.py`. `tests/test_k_anonymity.py` |
| **INV-7** | **The system refuses rather than guesses.** Below a retrieval confidence threshold, the answer is "I couldn't find this on Laurier's site" plus the human contact for that area. | `app/llm/answer.py`. Measured by the eval harness's refusal set. |

---

## 4. Architecture

### 4.1 System overview

```
                  ┌───────────────────────────────────────────┐
                  │            wlu.ca (public web)            │
                  └──────────────────┬────────────────────────┘
                                     │ scheduled crawl (robots-respecting)
                  ┌──────────────────▼────────────────────────┐
                  │  INGEST PIPELINE                          │
                  │  fetch → extract → chunk → embed → upsert  │
                  └──────────────────┬────────────────────────┘
                                     │
                  ┌──────────────────▼────────────────────────┐
                  │  PostgreSQL + pgvector                    │
                  │  documents · chunks · embeddings          │
                  │  questions(redacted) · clusters · reports │
                  └──────────────────┬────────────────────────┘
                                     │
   ┌─────────────┐   HTTP/JSON   ┌───▼──────────────────────────┐   redacted   ┌──────────┐
   │  Next.js    │──────────────▶│  FastAPI                     │─────────────▶│ Claude   │
   │  (student   │◀──────────────│  /ask  /health  /trends      │◀─────────────│ API      │
   │   chat +    │   SSE stream  │  retrieval · safety · redact │              └──────────┘
   │  dashboard) │               │  citation validation         │
   └─────────────┘               └──────────────────────────────┘
```

### 4.2 Repository layout

```
locah-ai/
├── docs/                     # SDD, BRD, ADRs, runbooks
├── backend/
│   ├── app/
│   │   ├── api/              # FastAPI routers — HTTP only, no logic
│   │   ├── core/             # config, redaction, safety, errors
│   │   ├── ingest/           # crawler, extractor, chunker, embedder
│   │   ├── retrieval/        # hybrid search, reranking, conflict detection
│   │   ├── llm/              # prompt templates, answer synthesis, validation
│   │   └── analytics/        # question logging, clustering, reports
│   ├── migrations/           # Alembic
│   └── tests/
├── frontend/                 # Next.js (App Router) + Tailwind
├── eval/                     # gold set + scoring harness
└── scripts/                  # one-off ops scripts
```

### 4.3 Team decomposition (~10 volunteers, 5 pods)

| Pod | Owns | Size | Primary deliverable |
|---|---|---|---|
| **Ingest** | `app/ingest/`, crawl scheduling | 2 | A refreshed, deduplicated knowledge base |
| **Retrieval** | `app/retrieval/`, `app/llm/` | 2–3 | Answer quality: recall, citations, conflicts, refusal |
| **Platform** | `app/api/`, `app/core/`, DB, deploy, CI | 2 | A running service with the invariants enforced |
| **Frontend** | `frontend/` | 2 | Chat UI + trends dashboard |
| **Eval & Research** | `eval/`, advisor/student interviews | 1–2 | The gold set, the weekly quality number, interview findings |

Pods own *directories*, so merge conflicts are rare and a new volunteer can be onboarded into one pod without reading the whole system.

---

## 5. Component design

### 5.1 Ingest pipeline

**Crawler** (`ingest/crawler.py`)
- Seeds: advising, academic calendar, co-op, important dates, registrar, wellness, accessible learning, financial aid.
- Scope: hostname must match the `*.wlu.ca` allowlist. **[INV-1]**
- Politeness: obeys `robots.txt`, ≥1 s delay per host, single concurrent connection per host, descriptive `User-Agent` with a contact address.
- Depth cap, page cap, and content-type filter (`text/html`, `application/pdf`).
- Persists `documents(url, http_status, content_hash, fetched_at, etag)`. Unchanged `content_hash` short-circuits re-embedding.

**Extractor** (`ingest/extract.py`)
- HTML → main content via `trafilatura`; strips nav, footer, cookie banners.
- PDF → text via `pypdf`, page-numbered.
- Preserves heading hierarchy as a breadcrumb string, used later as chunk context.

**Chunker** (`ingest/chunk.py`)
- Heading-aware recursive split, target 800 tokens, 120-token overlap.
- Each chunk carries: `document_id`, `heading_path`, `char_range`, `url` (with `#anchor` when a heading id exists so citations deep-link).

**Embedder** (`ingest/embed.py`)
- Batched embedding calls; retry with exponential backoff; upsert into `chunks.embedding vector(N)`.
- Model choice is a config value, not a hardcode — see ADR-003.

**Scheduling**: nightly full pass over high-churn seeds (dates, deadlines), weekly full crawl. A GitHub Actions cron triggers a backend job endpoint.

### 5.2 Retrieval

**Hybrid search** (`retrieval/search.py`)
- Dense: pgvector cosine over `chunks.embedding`, top-k=30.
- Sparse: Postgres full-text (`tsvector`) over chunk text, top-k=30.
- Fusion: Reciprocal Rank Fusion, then trim to top-8 for the context window.

**Conflict detection** (`retrieval/conflict.py`) — **[F3]**
- Extract atomic factual candidates (dates, GPA thresholds, dollar amounts, deadlines) from the top chunks via regex + a lightweight structured LLM extraction.
- Group by normalized fact key (e.g. `coop.gpa_threshold`). If two distinct values exist across different `document_id`s, emit a `Conflict{key, values[], sources[]}`.
- The answer template renders conflicts explicitly: *"Two Laurier pages state different values — X on \<page A\>, Y on \<page B\>. Confirm with \<office\>."* Never silently pick one.

**Confidence & refusal** (`retrieval/confidence.py`) — **[INV-7]**
- Score = f(top-1 similarity, score gap between top-1 and top-5, count of chunks above threshold).
- Below threshold → refusal path with the routing contact for the detected topic.

### 5.3 LLM layer

- **Provider**: Anthropic Claude (see ADR-002). Single egress module, `llm/client.py`, so redaction cannot be bypassed. **[INV-2]**
- **System prompt** (`llm/prompts.py`) enforces: answer only from provided context; cite with `[n]` markers mapped to source URLs; state uncertainty; never invent a policy, deadline, or dollar amount; never give wellbeing advice.
- **Citation validator** (`llm/validate.py`) — **[INV-4]**: parses `[n]` markers, verifies each maps to a supplied chunk, and flags factual sentences with no marker. Failure → regenerate once, then refuse.
- **Streaming**: Server-Sent Events to the frontend; citations resolved and attached after the stream closes.

### 5.4 Safety & redaction

**Redaction** (`core/redaction.py`) — **[INV-2]**
- Regex + validated patterns for: Laurier student numbers, emails, phone numbers, postal codes; named-entity pass for person names.
- Replaces with stable placeholders (`⟨PERSON_1⟩`) held in an in-request map; restored locally on the way out. The map is never written to storage.

**Safety gate** (`core/safety.py`) — **[INV-5]**
- Classifies a question for wellbeing/crisis/accommodation signal.
- Permitted effects: prepend crisis and support resources, add a human contact, mark the interaction for a coarse-grained aggregate count.
- There is deliberately **no code path** by which this classifier can suppress, delay, downrank, or auto-close anything. Reviewers should reject any PR that adds one.

### 5.5 Analytics & trends dashboard — **[F5]**

**Logging** (`analytics/logging.py`) — **[INV-3]**
- Writes: `questions(id, redacted_text, topic_label, retrieval_confidence, was_refused, had_conflict, asked_at)`.
- Does **not** write: IP, user agent, session identity, cookie, or anything joining two questions to one person.

**Weekly clustering** (`analytics/cluster.py`)
- Embed redacted questions → HDBSCAN (or k-means with silhouette selection) → label each cluster with a Claude-generated short description.
- Produces `clusters(week, label, size, sample_questions[], mean_confidence, refusal_rate)`.

**Report** (`analytics/report.py`) — **[INV-6]**
- Ranks clusters by size × (1 − answer quality), i.e. *what students ask most and we answer worst* — the fix-at-the-source list.
- Suppresses any cluster with `size < 5`. Wellbeing clusters reported only as a single coarse category with a count.

**Dashboard** (frontend `/trends`): weekly top questions, refusal rate over time, conflicts detected with their URLs, and coverage gaps. This is the artefact reported back to the Students' Union.

### 5.6 Frontend

- Next.js App Router, TypeScript, Tailwind, server components where possible.
- Routes: `/` (chat), `/trends` (dashboard), `/about` (what it is, what it does not do, privacy posture — publicly visible, non-negotiable).
- Chat UI shows citations inline as numbered chips that expand to the source URL and quoted passage. **The citation is part of the answer, not a footnote.**
- Accessibility: WCAG 2.1 AA, keyboard-navigable, screen-reader tested. A tool for students who are stuck must work for students using assistive technology.

---

## 6. Data model

```sql
-- Knowledge base
documents(
  id            uuid pk,
  url           text unique not null,
  title         text,
  content_hash  text not null,
  http_status   int,
  content_type  text,
  fetched_at    timestamptz not null,
  is_active     bool default true
);

chunks(
  id            uuid pk,
  document_id   uuid fk -> documents on delete cascade,
  ordinal       int not null,
  heading_path  text,
  text          text not null,
  token_count   int,
  embedding     vector(1024),
  tsv           tsvector generated,
  url_anchor    text
);
create index on chunks using hnsw (embedding vector_cosine_ops);
create index on chunks using gin (tsv);

-- Analytics — deliberately identity-free  [INV-3]
questions(
  id                  uuid pk,
  redacted_text       text not null,
  topic_label         text,
  retrieval_confidence real,
  was_refused         bool,
  had_conflict        bool,
  asked_at            timestamptz not null
);

clusters(
  id            uuid pk,
  week_start    date not null,
  label         text not null,
  size          int not null,
  mean_confidence real,
  refusal_rate  real,
  sample_questions text[]
);

conflicts(
  id            uuid pk,
  fact_key      text not null,
  values        jsonb not null,   -- [{value, document_id, url}]
  first_seen    timestamptz,
  resolved      bool default false
);
```

**Note the absence of a `users` table.** That is intentional and is the structural expression of INV-3.

---

## 7. API contract

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/ask` | `{question}` → SSE stream of answer tokens, then a terminal `{citations[], conflicts[], resources[], confidence, refused}` frame |
| `GET` | `/api/v1/trends?week=` | Weekly report — suppressed per INV-6 |
| `GET` | `/api/v1/conflicts` | Currently detected contradictions between Laurier pages |
| `GET` | `/api/v1/health` | Liveness + KB freshness (`last_crawl_at`, `active_documents`) |
| `POST` | `/api/v1/admin/crawl` | Trigger ingest (bearer token, CI/cron only) |

Errors: RFC 7807 problem+json. Rate limit: 20 questions / 10 min per IP, enforced at the edge — the IP is used for rate limiting and never stored with the question.

---

## 8. Quality: the evaluation harness — **[F6]**

Quality is a number we publish weekly, not a vibe.

**Gold set** (`eval/gold/`): ~150 questions in five families, each with a human-verified answer and the URL that proves it.
1. **Factual** — "What GPA do I need for co-op?"
2. **Navigational** — "Who is my advisor if I'm in the BSc Computer Science program?"
3. **Conflict** — questions whose Laurier sources are known to disagree; correct behaviour is *surfacing both*.
4. **Refusal** — questions Laurier's public site genuinely does not answer; correct behaviour is *refusing with a contact*.
5. **Support-surfacing** — questions where the right behaviour includes naming a published support service.

**Metrics**
| Metric | Definition | Semester-1 target |
|---|---|---|
| Answer accuracy | Graded correct against gold, LLM-judged + 20% human-audited | ≥ 85% on factual |
| Citation validity | % of cited URLs that actually contain the claim | ≥ 95% |
| Hallucination rate | Factual claims with no supporting chunk | ≤ 2% |
| Correct refusal | % of refusal-set questions refused | ≥ 90% |
| False refusal | % of answerable questions wrongly refused | ≤ 10% |
| P95 latency | First token | ≤ 2.5 s |

CI runs a 40-question smoke subset on every PR; the full set runs nightly and on release. **A release that regresses accuracy or citation validity does not ship.**

---

## 9. Non-functional requirements

- **Availability**: best-effort; this is a volunteer-run pilot. Target 99% during term, no on-call.
- **Cost**: ≤ CAD $60/month at pilot scale. Embeddings are the fixed cost; generation scales with usage. Cost dashboard and a hard monthly cap that degrades to refusal-with-contact rather than surprise billing.
- **Security**: no secrets in the repo; all config via environment. Dependabot on. A `SECURITY.md` with a disclosure address.
- **Privacy**: the invariants in §3 are the privacy design. A public `/about` page states them in plain language.
- **Licensing**: crawled content is Laurier's; we index and quote with attribution and always link to the source. We do not republish pages wholesale.

---

## 10. Deployment

| Environment | Stack | Trigger |
|---|---|---|
| Local | `docker compose up` — Postgres+pgvector, FastAPI reload, Next dev | manual |
| Staging | Backend on Railway/Fly.io, frontend on Vercel, Neon/Supabase Postgres | push to `main` |
| Production | Same, separate project + database | tagged release |

CI (`.github/workflows/ci.yml`): lint (ruff, eslint) → typecheck (mypy, tsc) → unit tests → invariant tests → eval smoke subset.

---

## 11. Semester 1 milestones

| Sprint | Weeks | Goal | Exit criterion |
|---|---|---|---|
| **S0 — Foundations** | 1–2 | Repo, CI, docker-compose, schema, pod assignment | `docker compose up` gives a working skeleton on every member's machine |
| **S1 — Ingest** | 3–4 | Crawler + extractor + chunker + embedder | ≥ 2,000 wlu.ca chunks indexed; re-crawl is idempotent |
| **S2 — Answer** | 5–6 | Retrieval + generation + citations + refusal | End-to-end cited answer to a real question in the browser |
| **S3 — Trust** | 7–8 | Conflict surfacing, safety gate, redaction, `/about` | All INV tests green; gold set v1 (150 q) complete |
| **S4 — Evidence** | 9–10 | Analytics logging, clustering, trends dashboard | A real weekly report generated from real questions |
| **S5 — Pilot** | 11–12 | Closed pilot with a student cohort + advisor interviews | ≥ 100 real questions answered; metrics table populated |
| **S6 — Report** | 13 | Metrics, findings, SU report, Phase 2 proposal | Report delivered to the Students' Union |

Interviews with advisors and faculty run in parallel from week 1 — the proposal commits to them, and they should shape S3–S5, not merely validate them.

---

## 12. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Laurier ICT objects to crawling | Project stops | Respect robots.txt from day one; notify ICT proactively in week 1; be a good citizen and be seen to be |
| Volunteer attrition mid-term | Pods stall | Pods of 2, documented interfaces, no single-owner critical path; every module has a README |
| Answer quality too low to be useful | Pilot fails honestly | Eval harness from S3, not S6 — we find out in week 7, not week 13 |
| Scope creep into MyDegree/SSO | Blocks on ICT approval the club doesn't have | Phase gate is explicit in this SDD; PRs touching auth are rejected in Semester 1 |
| A student in crisis uses it | Serious harm | INV-5; resources surfaced prominently; `/about` states clearly this is not a support service |
| LLM cost overrun | Budget blown | Hard monthly cap, cached embeddings, cost dashboard |

---

## 13. Architecture Decision Records

- **ADR-001 — Python backend + Next.js frontend.** RAG, evaluation, and NLP tooling is materially better in Python; the student-facing surface is materially better in React. The split also maps cleanly onto pods with different skill levels.
- **ADR-002 — Anthropic Claude as the model provider.** Strong instruction-following for citation discipline and refusal behaviour, which is the core quality risk here. Provider is behind one interface (`llm/client.py`) so it can be swapped.
- **ADR-003 — Postgres + pgvector rather than a dedicated vector database.** One database for documents, embeddings, and analytics; free tier is sufficient at pilot scale; one fewer vendor account for a student club to hand over each year. Revisit above ~1M chunks.
- **ADR-004 — Hybrid dense + sparse retrieval.** University pages are full of exact tokens (course codes, `CP104`, dates, GPA numbers) that dense retrieval alone handles poorly.
- **ADR-005 — No user accounts in the MVP.** Accounts create a PII surface with no MVP benefit, and their absence is the structural enforcement of INV-3.

---

## 14. Open questions

1. Does Laurier ICT have a preferred contact and a position on crawl rate? *(Owner: club exec, week 1)*
2. Will advisors participate in interviews this term, and how many? *(Owner: Eval & Research pod)*
3. Is there an existing FOSSA/SU hosting arrangement we should use instead of Vercel/Railway?
4. Who holds the credentials and the domain after this executive term ends? *(Continuity — must be answered before the pilot.)*
