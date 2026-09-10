# Ingest pipeline — Ingest pod

Turns Laurier's public web pages into an indexed, refreshable knowledge base.

`crawler.py` → `extract.py` → `chunk.py` → `embed.py`

**Invariant you own: INV-1.** Only public `wlu.ca` pages enter the index. The allowlist is in `core/config.py`; `robots.txt` is respected without exception; the crawler identifies itself with a contact address.

Spec: [SDD §5.1](../../../docs/SDD.md#51-ingest-pipeline)
