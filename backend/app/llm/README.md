# LLM layer — Retrieval pod

This pod owns `app/llm/` **and** `app/retrieval/`.

The single egress path to the model provider. Everything outbound goes through `client.py` after `app/core/redaction.py`, which is what makes INV-2 enforceable in one place.

`prompts.py` (citation discipline, refusal, no wellbeing advice) · `answer.py` (synthesis) · `validate.py` (citation validation — **INV-4**)

Spec: [SDD §5.3](../../../docs/SDD.md#53-llm-layer)
