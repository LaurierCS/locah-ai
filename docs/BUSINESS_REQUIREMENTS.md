# LOCAH.ai — Business Requirements

Owner: Laurier Computing Society · Sponsor: Wilfrid Laurier University Students' Union
Status: Draft v0.1 — Semester 1
Last updated: 2026-09-10

---

## 1. Business context

Laurier publishes accurate information that students cannot reliably find. The cost is paid twice: by students who miss requirements and deadlines, and by advisors and faculty who answer the same question dozens of times with no mechanism for turning that repetition into a fixed web page.

LOCAH.ai is a student-built assistant over Laurier's public information. Its business value is not "a chatbot" — it is **reducing time lost to information that is already published**, and **producing evidence about where Laurier's information fails**, which the university currently does not have.

## 2. Stakeholders

| Stakeholder | Interest | What they need from us |
|---|---|---|
| Students | Fast, correct, cited answers; discovering support they didn't know existed | A tool that works and never invents a deadline |
| Academic advisors (9 teams) | Fewer repeat questions; visibility into what students are stuck on | Evidence, and confidence it will not misinform their students |
| Faculty | Fewer routine emails | The same |
| Students' Union (funder) | Measurable student benefit for the money | An honest pilot report with real numbers |
| FOSSA | Technical soundness; open-source posture | A public repo, real engineering practice |
| Laurier ICT | Safe crawling; no privacy exposure; no shadow IT | Proactive contact, robots-respecting crawler, a stated privacy design |
| Laurier Computing Society | Members learn real engineering; project survives exec turnover | Documented system, pods, continuity plan |

## 3. Business objectives

| ID | Objective | Success measure (end of Semester 1) |
|---|---|---|
| BO-1 | Answer common student questions correctly and verifiably | ≥ 85% accuracy on the factual gold set; ≥ 95% citation validity |
| BO-2 | Never misinform | ≤ 2% hallucination rate; ≥ 90% correct refusal on unanswerable questions |
| BO-3 | Surface support services at the moment of need | Support resources surfaced on 100% of questions that touch wellbeing, accessibility, financial aid, or advising |
| BO-4 | Produce evidence Laurier can act on | ≥ 8 weekly trend reports; a ranked list of the top recurring questions and the pages that should be fixed |
| BO-5 | Demonstrate the privacy posture in practice, not just on paper | All privacy invariants test-enforced and independently reviewable in a public repo |
| BO-6 | Give ~10 club members real engineering experience | Every member merges reviewed code; every module has a documented owner |
| BO-7 | Report honestly, including failure | A pilot report delivered to the SU stating measured results, whether or not they are good |

## 4. Business requirements

### 4.1 Functional

| ID | Requirement | Priority |
|---|---|---|
| BR-1 | The system shall answer student questions about Laurier's publicly published information in plain language. | Must |
| BR-2 | Every answer shall cite the Laurier page(s) it came from, so the answer can be checked against the authority. | Must |
| BR-3 | Where official Laurier pages disagree, the system shall surface the conflict with both sources rather than choose one. | Must |
| BR-4 | The system shall surface relevant published Laurier support services when a question touches wellbeing, accessibility, financial aid, or advising. | Must |
| BR-5 | The system shall state that it does not know, and route to a named human contact, rather than guess. | Must |
| BR-6 | The system shall refresh its knowledge base on a schedule so answers reflect current pages. | Must |
| BR-7 | The system shall produce a weekly de-identified report of the most frequent and worst-answered questions. | Must |
| BR-8 | The system shall publish a plain-language page stating what it is, what it does not do, and how it handles information. | Must |
| BR-9 | The system shall record detected contradictions between Laurier pages for reporting to the relevant office. | Should |
| BR-10 | The advisor triage tool (classification, drafted replies, urgency escalation). | **Phase 2** |
| BR-11 | Personalised degree guidance via MyDegree + SSO. | **Phase 3 — requires ICT sponsorship and formal privacy review** |

### 4.2 Constraints and policy requirements

| ID | Requirement |
|---|---|
| BR-C1 | The knowledge base shall contain public web pages only. No student records, internal systems, or proprietary documents. |
| BR-C2 | No personally identifying information shall reach a third-party model provider. |
| BR-C3 | Message and question content shall not be retained in identifiable form. |
| BR-C4 | The system shall not screen, diagnose, or counsel, and shall generate no wellbeing advice of its own. |
| BR-C5 | A distress signal may only escalate to a human. It shall never suppress, de-prioritize, or auto-resolve. |
| BR-C6 | Aggregate reports shall suppress any category below 5 students; wellbeing categories at the coarsest useful grain. |
| BR-C7 | The system shall send nothing to a student autonomously. In Phase 2, a human sends every reply. |
| BR-C8 | The crawler shall respect `robots.txt` and rate-limit politely, and shall identify itself with a contact address. |
| BR-C9 | Integration with any Laurier system requires ICT sponsorship and a completed privacy review beforehand. |

### 4.3 Operational

| ID | Requirement |
|---|---|
| BR-O1 | Running cost shall not exceed CAD $60/month at pilot scale, with a hard cap that degrades gracefully. |
| BR-O2 | The system shall be operable by volunteer students with no on-call rotation. |
| BR-O3 | Credentials, domain, and hosting accounts shall be held by the club, with a documented handover for executive turnover. |
| BR-O4 | The repository shall be public and documented well enough that a new member can contribute in their first week. |

## 5. Assumptions

- Laurier's public pages remain crawlable and ICT does not object to a polite, identified crawler.
- ~10 volunteer students remain available across a 13-week term at roughly 4–6 hours/week.
- SU funding covers hosting and model API costs at pilot scale.
- Advisors will participate in interviews, but the MVP does not depend on their participation to function.

## 6. Dependencies

| Dependency | Owner | Needed by |
|---|---|---|
| SU funding decision | Students' Union | Sprint 0 |
| ICT notification and crawl posture | Club exec | Sprint 1 |
| Anthropic API access + billing | Club exec | Sprint 2 |
| Hosting accounts (Vercel, Railway/Fly, Neon/Supabase) | Platform pod | Sprint 0 |
| Advisor interview access | Club exec + Eval pod | Sprint 3 |
| Pilot student cohort | Club exec | Sprint 11 |

## 7. Out of scope for Semester 1

Advisor triage tooling · MyDegree/SSO integration · any authenticated student data · native mobile apps · any autonomous messaging to students · non-Laurier data sources.

## 8. Exit criteria for the pilot

At the end of Semester 1 the club reports to the Students' Union:

1. How many real questions were answered.
2. Measured accuracy and citation validity against a reviewed sample.
3. The ranked list of recurring questions that should be fixed at the source.
4. Contradictions found between official Laurier pages.
5. A recommendation: continue to Phase 2, or stop.

Per the funding proposal: **if it is not measurably reducing time spent on information that is already published, we say so and the project ends there.**
