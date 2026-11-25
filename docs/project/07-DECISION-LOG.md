# Decision log

| | |
|---|---|
| Version / date | 1.0 · 2026-11-25 |
| Owner | Shreya Joshi |
| Related | [PRD](02-PRD.md) · [Risk register](06-RISK-REGISTER.md) · [Architecture](../architecture/ARCHITECTURE_AND_WORKFLOWS.md) |

Each entry: the context, the options weighed, the decision and what follows from it. Sprint ids point to [SPRINTS.md](../sprints/SPRINTS.md).

| ID | Decision | Context and options | Consequences | Sprint |
|---|---|---|---|---|
| D-01 | **PostgreSQL is both the system of record and the work queue** (`FOR UPDATE SKIP LOCKED`, leases) | Options: a broker (Redis, RabbitMQ) or the database. One store gives transactional state changes and enqueueing and one less service | At-least-once work with idempotency keys; throughput ceiling lower than a broker, acceptable at this scale | S0 |
| D-02 | **n8n sequences, the backend decides** | Options: put logic in workflows or keep n8n to sequencing, polling, retries and timeouts. Workflows are hard to test | The backend owns every state transition; n8n holds no credentials and no state; workflows are generated from code and checked in CI | S0 |
| D-03 | **Static analysis only, never execute the repository** | Options: run the code or tests for richer facts, or parse only. Executing untrusted code is a security risk and non-deterministic | Edges are labelled verified, inferred or unresolved; dynamic behaviour is a stated limitation | S0 |
| D-04 | **Retrieval-only fallback when the model is unavailable** | Options: fail, or return the retrieved source locations. Failing hides what Raven did find | Users always get cited locations; confirmed in practice when the LLM account ran out of credit | S0, S6 |
| D-05 | **Confidence is a rule over evidence, not a model score** | Options: ask the model for a probability, or compute from citations and retrieval. A model's own confidence cannot be explained | High, medium or low with a stated rule; explainable and testable | S1 |
| D-06 | **Scope: public Python/FastAPI repositories only** | Options: many languages and private repositories, or one stack done well. Accuracy needs labelled ground truth per stack | Other languages get modules and imports only; private access deferred (B-12) | S0 |
| D-07 | **Measure quality with a versioned benchmark and gates; only raise thresholds** | Options: assert quality, or measure against hand-labelled repositories with CI gates | The benchmark found 5 defects; thresholds only ever raised | S4, S5 |
| D-08 | **React with only `react` and `react-dom`, plain CSS; reuse the graph engine** | Options: a component library and state manager, or minimal dependencies. Fewer dependencies reduce supply-chain risk | A test forbids new dependencies; styling is hand-written | S6 |
| D-09 | **Cache validated AI answers per commit** | Options: no cache, a time-based cache, or key on the exact code. A commit is immutable | Key = repository, commit, analyzer, prompt, model, normalised question; only model answers judged sufficient are cached; shared across users of the same public repository | S13 |
| D-10 | **Usage derived from existing tables, not a second counter** | Options: a usage counter table or compute from jobs and chat messages. Counters drift | Quotas and spend read the tables that already record usage; one source of truth | S13 |
| D-11 | **Map: architecture first, then groups, then files** | Context: the all-files graph was unreadable and scrolling zoomed instead of panning. Options: tune the graph, or change the model of navigation | Three levels; the old graph kept as "Detailed file graph"; scroll pans, ⌘/Ctrl + scroll zooms | S15 |
| D-12 | **Pull-request verdict renamed "review priority"** and rewritten in plain language | Context: "risk: high" read as "has bugs" and disagreed with another reviewer. Options: keep the label with a footnote, or change what it claims | Three levels with reasons, proven-or-guess labels and a "reads structure, not logic" note; false alarms fixed (removed tests, unused removals) | S15 |
| D-13 | **Layer new code onto the existing image while Docker could not reach PyPI** | Options: wait for the network, or build a thin layer on the working image | Unblocked local testing; recorded as a limitation; the from-scratch build was verified later (B-03 to recreate the stack) | S12, S13 |
| D-14 | **Publish with no licence file** (all rights reserved) | Context: public repository for a portfolio. Options: MIT or none. The owner wants to show the work, not grant reuse | Others may read but not reuse the code; revisit if reuse is wanted | S16 |
