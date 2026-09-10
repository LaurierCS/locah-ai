## What this changes

<!-- One paragraph. Link the issue. -->

## Invariant checklist

See [SDD §3](../docs/SDD.md#3-invariants). Tick what applies, or write N/A.

- [ ] **INV-1** No non-public source enters the knowledge base.
- [ ] **INV-2** All text sent to the model provider passes through `core/redaction.py`.
- [ ] **INV-3** Nothing persisted links a question to a person.
- [ ] **INV-4** No answer path can emit a factual claim without a resolvable citation.
- [ ] **INV-5** The safety gate gained no suppression or downranking path.
- [ ] **INV-6** Aggregate output suppresses categories below k=5.
- [ ] **INV-7** Low-confidence retrieval refuses rather than guesses.

## How I tested it
