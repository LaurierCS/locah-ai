# API routers — Platform pod

HTTP only, no business logic. Routes are declared here and call into ingest, retrieval, llm, and analytics.

Until S2, the only live route lives in `app/main.py` (`GET /api/v1/health`). Move routers here as `/ask`, `/trends`, `/conflicts`, and `/admin/crawl` land.

Contract: [SDD §7](../../../docs/SDD.md#7-api-contract).
