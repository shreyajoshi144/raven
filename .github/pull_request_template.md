## What and why
<!-- One or two sentences: the change and the problem it solves. Link the backlog item (B-xx) or defect (DEF-xx) if there is one. -->

## Evidence
- [ ] Tests added or updated (a defect fix has a test that failed before the fix)
- [ ] `ruff check backend/app backend/tests backend/evals` is clean
- [ ] `python -m pytest -q` passes (real PostgreSQL)
- [ ] Benchmark gates unaffected, or the change is explained (`python -m evals run --suite smoke`)
- [ ] `python3 scripts/check_docs.py` passes; CHANGELOG and the affected docs updated
- [ ] Migration is additive and has a downgrade; a backup is noted if it touches data

## Risk
<!-- What could this break? Link the risk (R-xx) if it changes one. -->
