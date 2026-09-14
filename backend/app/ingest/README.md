# Ingest pipeline — Ingest pod

Turns Laurier's public web pages into an indexed, refreshable knowledge base.

`crawler.py` → `extract.py` → `chunk.py` → `embed.py`

**Invariant you own: INV-1.** Only public Laurier pages enter the index. The hostname allowlist is `CRAWL_ALLOWLIST` in `app/core/config.py` (not a `*.wlu.ca` wildcard); `robots.txt` is respected without exception; the crawler identifies itself with a contact address.

Embedding model is TBD in S1. Schema is `vector(1024)` until then.

Spec: [SDD §5.1](../../../docs/SDD.md#51-ingest-pipeline)
