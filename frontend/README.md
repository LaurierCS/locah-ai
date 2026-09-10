# Frontend — Frontend pod

Next.js App Router + TypeScript + Tailwind.

| Route | Purpose |
|---|---|
| `/` | Chat. Citations are numbered chips inline in the answer — **part of the answer, not a footnote**. Conflicts render as two labelled sources side by side. |
| `/trends` | Weekly report: top questions, refusal rate over time, detected conflicts, coverage gaps. |
| `/about` | Plain-language statement of what LOCAH is, what it does not do, and how it handles information. Non-negotiable and public. |

**Accessibility is a requirement, not a nice-to-have.** WCAG 2.1 AA, keyboard navigable, screen-reader tested. A tool for students who are stuck must work for students using assistive technology.

Backend contract: [SDD §7](../docs/SDD.md#7-api-contract). `/api/v1/ask` streams tokens over SSE, then sends a terminal frame with citations, conflicts, resources, confidence, and the refusal flag.
