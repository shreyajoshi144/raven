"""Regression test: retrieval must return identical ranked evidence for identical inputs, including after re-analysing the same
commit (node ids differ per analysis, so ties must not be broken by database row order). Failed before stable tie-breakers."""
from app.core.db import new_session
from app.retrieval.search import retrieve
from evals.benchmark import Benchmark
from evals.runner import analyze


def _ranked(job_id, questions):
    with new_session() as db:
        return [[(e["path"], e["start_line"], e["end_line"], e["kind"], e["reason"]) for e in retrieve(db, job_id, q)] for q in questions]


def test_identical_inputs_return_identical_ranked_evidence():
    bm = Benchmark("v1")
    files = bm.files("fastapi_template")
    questions = [q.question for q in bm.truth["fastapi_template"].qa]
    first = analyze("fastapi/full-stack-fastapi-template", files)
    baseline = _ranked(first.job_id, questions)
    assert _ranked(first.job_id, questions) == baseline  # same analysis, asked again
    for _ in range(4):  # same commit, analysed again from scratch
        again = analyze("fastapi/full-stack-fastapi-template", files)
        assert _ranked(again.job_id, questions) == baseline


def test_evidence_always_lies_inside_the_file():
    """Empty files (e.g. __init__.py, 0 lines) must never yield a snippet; every snippet starts at line 1 or later."""
    from sqlalchemy import select

    from app.models import AnalysisFile
    bm = Benchmark("v1")
    for rid, full in (("shop_api", "raven-eval/shop_api"), ("fastapi_template", "fastapi/full-stack-fastapi-template")):
        an = analyze(full, bm.files(rid))
        with new_session() as db:
            lines = {f.path: f.line_count for f in db.execute(select(AnalysisFile).where(AnalysisFile.analysis_id == an.job_id)).scalars()}
            for q in bm.truth[rid].qa:
                for e in retrieve(db, an.job_id, q.question):
                    assert 1 <= e["start_line"] <= e["end_line"] <= lines[e["path"]], (q.id, e["path"], e["start_line"], e["end_line"])
