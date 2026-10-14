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

Not in this module yet: `confidence.py` (#9), `conflict.py` (#11), `/ask` wiring (#72 / #73).

## Tests

```bash
cd backend
uv run pytest tests/test_rrf.py tests/test_retrieval_search.py -q
```

`test_retrieval_search.py` needs Postgres with migrations applied (`async_session` skips if the DB is down). CI provides pgvector via `.github/workflows/ci.yml`.
