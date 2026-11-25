# Roadmap

| | |
|---|---|
| Version / date | 1.0 · 2026-11-25 |
| Related | [Milestones](04-MILESTONES.md) · [Backlog](05-PRODUCT-BACKLOG.md) · [Sprint history](../sprints/SPRINTS.md) |

## 1. Delivered (S0–S16, 2026-10-14 to 2026-11-25)
```mermaid
gantt
  title Raven delivery (actual)
  dateFormat YYYY-MM-DD
  axisFormat %b %d
  section Foundation
  S0 MVP (approximate dates)           :done, s0, 2026-10-14, 5d
  S1 Analyzer 1.1.0                    :done, s1, 2026-10-19, 1d
  section Verify and measure
  S2 UI and real-stack run             :done, s2, 2026-10-26, 1d
  S3 Documentation                     :done, s3, 2026-10-26, 1d
  S4 Evaluation framework              :done, s4, 2026-10-26, 1d
  S5 Defect fixes                      :done, s5, 2026-10-27, 6d
  section Productise
  S6 Sign-up, React UI, AI hardening   :done, s6, 2026-11-01, 1d
  S7 Package and plan                  :done, s7, 2026-11-01, 1d
  S8-S10 Intelligence upgrade          :done, s8, 2026-11-02, 2d
  section Launch preparation
  S11 Local deployment validation      :done, s11, 2026-11-03, 1d
  S12 UI redesign                      :done, s12, 2026-11-05, 1d
  S13 Operations hardening             :done, s13, 2026-11-07, 1d
  S14 Documentation and portfolio      :done, s14, 2026-11-23, 1d
  S15 Map and plain-language PR review :done, s15, 2026-11-24, 1d
  S16 Repository, CI, PM pack          :active, s16, 2026-11-25, 1d
```
Dates before S8 are approximate (see [SPRINTS.md](../sprints/SPRINTS.md)). S9 is dated to the day migration `0006` landed; the work around it ran 2026-11-02 to 2026-11-03.

## 2. Next, Now / Next / Later
Priorities follow the [backlog](05-PRODUCT-BACKLOG.md) (MoSCoW). No dates are committed: there is no deadline and the first two items depend on an LLM account being funded.

| Horizon | Item | Backlog | Why |
|---|---|---|---|
| **Now** | Record a green GitHub Actions run | B-02 | The first run failed at lint and was fixed; the pipeline is the proof the tests run elsewhere |
| **Now** | One successful live AI answer, then the benchmark with the judge | B-01 | The biggest unverified claim: answer quality with a real model |
| **Now** | Refresh the running local stack from the from-scratch image | B-03 | The running images were layered during a network outage |
| **Next** | Hosted demo on a small server with HTTPS, spend limits and real email | B-04, B-05 | A live link for reviewers; needs a domain and SMTP |
| **Next** | Five developer interviews on the Map and the pull-request page | B-09 | The core claim is still a hypothesis |
| **Next** | Alert thresholds on error rate, queue age and AI fallback rate | B-06 | The numbers exist; nothing watches them |
| **Later** | Semantic retrieval measured, then pgvector at scale | B-08 | Retrieval is the weakest measured area (hit@5 0.55) |
| **Later** | Private repositories through a GitHub App; posting review comments | B-12, B-13 | Larger audience; needs scoped credentials |
| **Later** | More languages; SSO and organisations | B-14, B-15 | Only after the FastAPI case is proven with users |

## 3. Roadmap principles
1. Verify before extending: no new capability while an existing claim is unverified.
2. Every feature ships with evidence (a test, a benchmark change or an observed run).
3. Cuts are recorded, not forgotten ([PRD §6](02-PRD.md#6-what-was-cut-and-why)).
