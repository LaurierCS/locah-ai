# LLM layer — Retrieval pod

This pod owns `app/llm/` **and** `app/retrieval/`.

The single egress path to the model provider. Everything outbound goes through `client.py` after `app/core/redaction.py`, which is what makes INV-2 enforceable in one place.

`routing.py` (topic detection, human contacts) · `answer.py` (refusal — INV-7; synthesis lands with #71) · `prompts.py` (citation discipline — #71) · `validate.py` (citation validation — INV-4, #8)

Spec: [SDD §5.3](../../../docs/SDD.md#53-llm-layer)

## Refusal path (`answer.py` + `routing.py`) — issue #9 [INV-7]

```python
from app.llm import build_refusal

refusal = build_refusal(question, chunks, threshold=optional_override)
if refusal is not None:
    # refusal.message  — ready-to-send string
    # refusal.topic    — e.g. "coop", "registrar", "advising"
    # refusal.contact  — HumanContact(office_name, url)
    # refusal.confidence — full ConfidenceAssessment for logging
    return refusal
# else: proceed to synthesis (#71)
```

`build_refusal` calls `assess_confidence` internally, so the caller only needs
the chunk list from `hybrid_search`. It returns `None` when confidence is
sufficient — the `#72` ask pipeline treats `None` as the green light for
synthesis.

### Refusal message format (INV-7)

```
I couldn't find this on Laurier's site. For help with this topic, please
contact <office_name>: <url>
```

### Topic routing (`routing.py`)

`detect_topic(question)` runs keyword patterns in priority order and returns
a topic key. `contact_for_topic(topic)` maps the key to a `HumanContact`.

| Topic | Keywords (examples) | Office |
|-------|---------------------|--------|
| `coop` | co-op, work term, experiential | Career & Experiential Learning |
| `registrar` | registrar, transcript, petition, appeal | Office of the Registrar |
| `financial` | OSAP, bursary, scholarship, tuition | Financial Aid |
| `wellbeing` | mental health, counselling, wellness | Student Wellness Centre |
| `accessibility` | accessible learning, ALC, accommodation | Accessible Learning Centre |
| `advising` | advisor, advising, registration *(default)* | Academic Advising |

All contact URLs are public Laurier student-portal pages from `ingest/seeds.yaml`.

## Tests

```bash
cd backend
uv run pytest tests/test_confidence.py tests/test_refusal.py -q
```

Both test files are pure unit — no Postgres or network required.
