# API routers — Platform pod

HTTP only, no business logic. Routes are declared here and call into ingest, retrieval, llm, and analytics.

Current active routes:
- `GET /api/v1/health`: Liveness check and KB freshness. Returns 200 OK if DB is reachable, 503 if not.

Contract: [SDD §7](../../../docs/SDD.md#7-api-contract).
