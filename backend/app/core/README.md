# Core — Platform pod

Config, redaction, and the safety gate. This directory is where the privacy commitments in the funding proposal become code.

**Invariants you own: INV-2 (redaction), INV-5 (one-way safety gate).**

INV-2 is enforced here (`redaction.py`) and at the LLM choke point (`app/llm/client.py`, Retrieval pod). Everything outbound must pass through `redact()` first.

Changes here need a Platform reviewer in addition to your pod reviewer.

Spec: [SDD §5.4](../../../docs/SDD.md#54-safety--redaction)
