"""DeepEval integration check (offline). Runs DeepEval's real GEval / Faithfulness / AnswerRelevancy metrics through the harness's
Judge adapter, driven by a scripted judge model. Verifies wiring only: the scores are meaningless.
Skipped unless DeepEval is installed (backend/requirements-eval.txt, separate virtualenv)."""
import json
import os
import typing

import pytest

os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")
pytest.importorskip("deepeval")

from deepeval.models import DeepEvalBaseLLM  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from evals.judge import Judge, JudgeConfig, _import_deepeval, deepeval_metrics  # noqa: E402


def _fill(tp):
    origin = typing.get_origin(tp)
    if origin in (list, typing.List):  # noqa: UP006
        return []
    if origin is typing.Union or str(origin) == "<class 'types.UnionType'>":
        return _fill([a for a in typing.get_args(tp) if a is not type(None)][0])
    if origin is typing.Literal:
        return typing.get_args(tp)[0]
    if isinstance(tp, type) and issubclass(tp, BaseModel):
        return {k: _fill(f.annotation) for k, f in tp.model_fields.items()}
    return {str: "yes", int: 8, float: 0.8, bool: True}.get(tp, "yes")


class ScriptedJudge(DeepEvalBaseLLM):
    def __init__(self):
        self.calls = 0
        super().__init__("scripted-judge")

    def load_model(self):
        return self

    def get_model_name(self):
        return "scripted-judge"

    def generate(self, prompt, schema=None, **kw):
        self.calls += 1
        return schema.model_validate(_fill(schema)) if schema else json.dumps({"score": 8, "reason": "scripted"})

    async def a_generate(self, prompt, schema=None, **kw):
        return self.generate(prompt, schema)


def test_deepeval_metrics_run_through_the_judge_adapter():
    dm = _import_deepeval()
    model = ScriptedJudge()
    j = Judge(JudgeConfig(provider="anthropic", per_minute=None, timeout_s=60, max_retries=0), deepeval_metrics(dm, model, 0.5), dm["LLMTestCase"])
    out = j.evaluate("How are passwords hashed?", "With hashlib.md5 over salt + password.", "hash_password uses hashlib.md5.",
                     ["app/core/security.py:9-10\ndef hash_password(password, salt): ..."])
    j.close()
    assert set(out) == {"correctness", "faithfulness", "answer_relevancy"}
    for name, r in out.items():
        assert r["error"] is None, (name, r["error"])
        assert 0.0 <= r["score"] <= 1.0 and isinstance(r["passed"], bool)
    assert model.calls >= 3
