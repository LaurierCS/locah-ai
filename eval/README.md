# Evaluation harness

Quality is a number we publish weekly, not a vibe. See [SDD §8](../docs/SDD.md#8-quality-the-evaluation-harness--f6).

## Gold set

`gold/*.jsonl` — one question per line:

```json
{"id":"coop-gpa-01","family":"factual","question":"What GPA do I need to apply for co-op?","expected":"...","source_url":"https://www.wlu.ca/...","must_cite":["https://www.wlu.ca/..."]}
```

Families: `factual`, `navigational`, `conflict`, `refusal`, `support`.

For `refusal` items, the correct behaviour is refusing with a named contact — `expected` describes that, not an answer.
For `conflict` items, the correct behaviour is surfacing *both* values with both URLs.

## Running

```bash
python -m eval.run --set gold/factual.jsonl        # full
python -m eval.run --smoke                          # 40-question CI subset
```

## Targets (end of Semester 1)

| Metric | Target |
|---|---|
| Factual accuracy | ≥ 85% |
| Citation validity | ≥ 95% |
| Hallucination rate | ≤ 2% |
| Correct refusal | ≥ 90% |
| False refusal | ≤ 10% |
