# Retrieval — Retrieval pod

Hybrid dense (pgvector) + sparse (Postgres FTS) search with reciprocal rank fusion, conflict detection, and confidence scoring.

**Invariants you own: INV-4 (every claim cited), INV-7 (refuse rather than guess).**

Course codes and dates are why we run sparse search alongside dense — see ADR-004.

Spec: [SDD §5.2](../../../docs/SDD.md#52-retrieval)
