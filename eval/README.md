# Evaluation harness

Quality is a number we publish weekly, not a vibe. See [SDD §8](../docs/SDD.md#8-quality-the-evaluation-harness--f6).

The harness and gold set land in **S3**. Until then this directory is the contract: file layout, families, and targets. CI does not run eval yet; once `eval.run` exists, a 40-question smoke subset gates every PR.

## Gold set

`gold/*.jsonl` — one question per line:

```json
{"id":"coop-gpa-01","family":"factual","question":"What GPA do I need to apply for co-op?","expected":"...","source_url":"https://www.wlu.ca/...","must_cite":["https://www.wlu.ca/..."]}
```

Families: `factual`, `navigational`, `conflict`, `refusal`, `support`.

For `refusal` items, the correct behaviour is refusing with a named contact — `expected` describes that, not an answer.
For `conflict` items, the correct behaviour is surfacing *both* values with both URLs.

## Running (once the harness exists)

```bash
python -m eval.run --set gold/factual.jsonl        # full
python -m eval.run --smoke                          # 40-question CI subset
```

Those commands are the planned interface from `eval/`. They will fail until S3.

## Targets (end of Semester 1)

| Metric | Target |
|---|---|
| Factual accuracy | ≥ 85% |
| Citation validity | ≥ 95% |
| Hallucination rate | ≤ 2% |
| Correct refusal | ≥ 90% |
| False refusal | ≤ 10% |
