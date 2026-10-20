# Retrieval — Retrieval pod

This pod owns `app/retrieval/` **and** `app/llm/`.

Hybrid dense (pgvector) + sparse (Postgres FTS) search with reciprocal rank fusion, conflict detection, and confidence scoring.

**Invariants you own: INV-4 (every claim cited — `llm/validate.py`), INV-7 (refuse rather than guess — `retrieval/confidence.py` + `llm/answer.py`).**

Course codes and dates are why we run sparse search alongside dense — see ADR-004.

Spec: [SDD §5.2](../../../docs/SDD.md#52-retrieval)

## Hybrid search (`search.py`) — issue #7

```python
from app.retrieval import hybrid_search

hits = await hybrid_search(session, question, encoder=optional_encoder)
```

| Constant | Value | Source |
|---|---|---|
| `DENSE_CANDIDATE_K` | 30 | SDD §5.2 cosine top-k |
| `SPARSE_CANDIDATE_K` | 30 | SDD §5.2 FTS top-k |
| `RRF_K` | 60 | standard RRF constant |
| final trim | `settings.retrieval_top_k` (default 8) | `app/core/config.py` |

Query embedding uses the same `embed_texts` / ADR-006 model as ingest. Pass `encoder=` in tests so CI never downloads SentenceTransformer.

Dense SQL uses `vector_to_pg_literal` from `app.ingest.embed`. Sparse SQL uses `plainto_tsquery('english', …)` so student questions cannot break `tsquery` syntax.

## Confidence scoring (`confidence.py`) — issue #9 [INV-7]

```python
from app.retrieval import assess_confidence

assessment = assess_confidence(hits)
if assessment.should_refuse:
    # hand off to llm/answer.py build_refusal
    ...
```

`assess_confidence` takes the `list[RetrievedChunk]` from `hybrid_search` and
returns a `ConfidenceAssessment` without issuing any additional DB queries —
it uses `RetrievedChunk.dense_distance` directly.

### Scoring formula

Three signals are weighted into a composite score in [0, 1]:

| Signal | Definition | Weight |
|--------|------------|--------|
| `top1` | `max(0, 1 − dense_distance[0])` | 0.55 |
| `gap` | `min((top1_sim − rank5_sim) / 0.15, 1.0)` | 0.25 |
| `support` | `min(count(sim ≥ threshold) / 3, 1.0)` | 0.20 |

`rank5` uses `chunks[min(5, n) − 1]`, so it degrades gracefully with fewer than five results. A sparse-only hit (no dense leg) contributes `dense_similarity = 0`.

**Refusal rule:** `score < threshold` **or** empty chunk list → `should_refuse = True`.

The threshold defaults to `settings.confidence_threshold` (0.35) and can be overridden for tests.

`ConfidenceBreakdown` records all three raw signals plus the final score for
logging and the eval harness.

Not yet in this module: `conflict.py` (#11), `/ask` wiring (#72 / #73).

## Tests

```bash
cd backend
uv run pytest tests/test_rrf.py tests/test_retrieval_search.py tests/test_confidence.py -q
```

`test_retrieval_search.py` needs Postgres with migrations applied (`async_session` skips if the DB is down). CI provides pgvector via `.github/workflows/ci.yml`.

`test_confidence.py` is pure unit — no Postgres or network required.
