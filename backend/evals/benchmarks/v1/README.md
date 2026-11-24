# Benchmark card: raven-eval v1 (1.0.0, 2026-10-26)

Hand-labelled ground truth for evaluating Raven. Full documentation: [docs/evaluation/AI_EVALUATION.md](../../../../docs/evaluation/AI_EVALUATION.md).

| Repo | Kind | Source | Labels |
|---|---|---|---|
| `shop_api` | synthetic | `repos/shop_api` (written for this benchmark) | `ground_truth/shop_api.json` |
| `clean_service` | synthetic | `repos/clean_service` | `ground_truth/clean_service.json` |
| `fastapi_template` | real | `repos/fastapi_template`: `fastapi/full-stack-fastapi-template` @ `b1125d8839482cb7bbae603ddc6d0081bf87532e`, `backend/` only, byte-identical, MIT (see `PROVENANCE.md`, `LICENSE`) | `ground_truth/fastapi_template.json` |

Contents: 27 Q&A items (7 unanswerable) with reference answers, key facts and evidence spans · 30 routes · 25 data models (4 ORM tables) · 100 internal import edges · readiness labels for 20–25 assessed rules per repo · 5 change-impact scenarios.

**Verification.** Labels were authored by the Raven maintainers (with Claude Code) by reading the source at the pinned revision. They have not been independently reviewed. `python -m evals validate` checks the following, and fails on any mismatch:
- every span is inside its file and contains its anchor text;
- each repository's content hash matches `benchmark.json`;
- impact expectations equal the closure over the labelled import edges;
- every relevant test is a real test file.

**Rules.**
- Source files here are test data: never import, execute or "fix" them. The synthetic repos contain deliberate bad patterns.
- Any change to a label or a source file requires a new benchmark version directory.
- `fastapi_template` must stay byte-identical to upstream; `python -m evals verify-sources` checks it (network).
