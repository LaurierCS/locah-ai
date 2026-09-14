# Frontend — Frontend pod

Next.js 16 App Router + TypeScript 5 + Tailwind CSS 4. Package manager: **pnpm** 12. Node 24+.

```bash
pnpm install
pnpm run dev
```

Next 16 dropped `next lint`, so `pnpm run lint` runs ESLint directly. ESLint 9 and TypeScript 5 are pinned because `eslint-config-next@16` does not yet support ESLint 10 / TypeScript 7.

| Route | Purpose |
|---|---|
| `/` | Chat. Citations are numbered chips inline in the answer — **part of the answer, not a footnote**. Conflicts render as two labelled sources side by side. (S2) |
| `/trends` | Weekly report: top questions, refusal rate over time, detected conflicts, coverage gaps. (S4) |
| `/about` | Plain-language statement of what LOCAH is, what it does not do, and how it handles information. Non-negotiable and public. |

**Accessibility is a requirement, not a nice-to-have.** WCAG 2.1 AA, keyboard navigable, screen-reader tested. A tool for students who are stuck must work for students using assistive technology.

Backend contract: [SDD §7](../docs/SDD.md#7-api-contract). `/api/v1/ask` streams tokens over SSE, then sends a terminal frame with citations, conflicts, resources, confidence, and the refusal flag. Next rewrites `/api/v1/*` to the FastAPI process (`BACKEND_URL`, default `http://localhost:8000`).
