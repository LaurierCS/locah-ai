# Retrieval — Retrieval pod

This pod owns `app/retrieval/` **and** `app/llm/`.

Hybrid dense (pgvector) + sparse (Postgres FTS) search with reciprocal rank fusion, conflict detection, and confidence scoring.

**Invariants you own: INV-4 (every claim cited — `llm/validate.py`), INV-7 (refuse rather than guess — `retrieval/confidence.py` + `llm/answer.py`).**

Course codes and dates are why we run sparse search alongside dense — see ADR-004.

Spec: [SDD §5.2](../../../docs/SDD.md#52-retrieval)
