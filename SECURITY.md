# Security & Privacy Disclosure

LOCAH.ai handles student questions. If you find a vulnerability — especially anything that could expose a question to another user, leak identifying information, or bypass the redaction layer — please report it privately rather than opening a public issue.

**Contact:** <security contact email — TBD>

Please include what you found, how to reproduce it, and what you think the impact is. We will acknowledge within 5 days.

## What we consider in scope

- Any path by which personally identifying information reaches the model provider (violates INV-2).
- Any path by which a question is persisted with identity (violates INV-3).
- Any path by which the safety gate can suppress or de-prioritize a message (violates INV-5).
- Aggregate reports that permit re-identification (violates INV-6).
- Standard web vulnerabilities: injection, SSRF via the crawler, auth bypass on admin endpoints.

See [docs/SDD.md §3](docs/SDD.md#3-invariants) for the full invariant list.
