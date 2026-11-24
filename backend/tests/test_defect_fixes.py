"""Regression tests for the four defects found by the evaluation benchmark (docs/evaluation/AI_EVALUATION.md §9).
Each test failed before its fix."""
import pytest

from app.analysis.archive import Limits, read_archive
from app.analysis.pyparse import extract_facts
from app.analysis.webparse import extract_web_facts
from tests.fixtures.sample_repo import make_tarball
from tests.helpers import analyze


# ------------------------------------------------------------------ 1. parsing compatibility
PY314_EXCEPT = '''import jwt
from app.core import security


def get_user(token):
    try:
        return jwt.decode(token, security.KEY)
    except InvalidTokenError, ValidationError:
        raise ValueError("bad token")


def other():
    return 1
'''


def test_python_314_unparenthesised_except_keeps_the_whole_file_with_exact_lines():
    f = extract_facts(PY314_EXCEPT, "app/deps.py")  # raised SyntaxError on Python 3.12 before the fix
    fns = {x["qualname"]: x for x in f["functions"]}
    assert (fns["get_user"]["line"], fns["get_user"]["end_line"], fns["other"]["line"]) == (5, 9, 12)
    assert any(i["module"] == "app.core" and i["line"] == 2 for i in f["imports"])
    assert [(e["line"], e["type"]) for e in f["excepts"]] == [(8, "(InvalidTokenError, ValidationError)")]
    assert f["parse_issues"] == [{"kind": "compat_rewrite", "start_line": 8, "end_line": 8,
                                  "detail": "Python 3.14 unparenthesised `except A, B:` read as `except (A, B):` (same meaning; line numbers unchanged)"}]
    assert f["line_count"] == 13


PARTIAL = "import os\n\n\ndef ok():\n    return os.getcwd()\n\n\ndef broken(:\n    return 2\n\n\nclass Model:\n    name = 'x'\n"


def test_unparseable_statement_is_skipped_and_reported_while_the_rest_keeps_exact_locations():
    f = extract_facts(PARTIAL, "app/mixed.py")
    assert [(x["qualname"], x["line"]) for x in f["functions"]] == [("ok", 4)]
    assert [(c["qualname"], c["line"]) for c in f["classes"]] == [("Model", 12)]
    issue = f["parse_issues"][0]
    assert (issue["kind"], issue["start_line"], issue["end_line"]) == ("skipped", 8, 9) and "SyntaxError" in issue["detail"]


def test_partially_parsed_files_are_reported_by_readiness_and_graph():
    g, r, _, _ = analyze({"app/__init__.py": "", "app/mixed.py": PARTIAL})
    f = next(x for x in r["findings"] if x["rule"] == "MAINT-PARSE-FAILURES")
    assert f["evidence"] == [{"path": "app/mixed.py", "start_line": 8, "end_line": 9, "note": "lines not parsed"}]
    assert any(gp["kind"] == "partial_parse" and gp["path"] == "app/mixed.py" and gp["line"] == 8 for gp in g.gaps)
    assert any(n.type == "class" and n.name == "Model" and n.start == 12 for n in g.nodes)


def test_a_file_with_nothing_parseable_is_still_a_parse_failure():
    with pytest.raises(SyntaxError):
        extract_facts("def (:\n", "app/bad.py")


# ------------------------------------------------------------------ 3. SQLModel ORM tables through a base class
SQLMODEL = '''from pydantic import BaseModel
from sqlmodel import Field, SQLModel


class UserBase(SQLModel):
    email: str


class User(UserBase, table=True):
    id: int | None = Field(default=None, primary_key=True)


class Direct(SQLModel, table=True):
    id: int = Field(primary_key=True)


class UserPublic(UserBase):
    id: int


class Plain(BaseModel):
    x: int


class NotATable(Plain, table=True):
    y: int
'''


def test_sqlmodel_table_declared_through_an_intermediate_base_is_an_orm_model():
    g = analyze({"app/__init__.py": "", "app/models.py": SQLMODEL})[0]
    kinds = {n.name: n.meta.get("model_kind") for n in g.nodes if n.type == "model"}
    assert kinds == {"UserBase": "pydantic", "User": "sqlalchemy", "Direct": "sqlalchemy", "UserPublic": "pydantic", "Plain": "pydantic", "NotATable": "pydantic"}


# ------------------------------------------------------------------ 4a. os.getenv is never "required at import"
def test_only_raising_environment_lookups_are_required_at_import():
    src = 'import os\n\nREQUIRED = os.environ["DATABASE_URL"]\nOPTIONAL = os.getenv("PAYMENT_API_KEY")\nALSO = os.environ.get("REDIS_URL")\n'
    r = analyze({"app/__init__.py": "", "app/config.py": src})[1]
    f = next(x for x in r["findings"] if x["rule"] == "CFG-REQUIRED-ENV-AT-IMPORT")
    assert [(e["path"], e["start_line"]) for e in f["evidence"]] == [("app/config.py", 3)] and f["evidence_total"] == 1


def test_getenv_alone_does_not_raise_the_finding():
    r = analyze({"app/__init__.py": "", "app/config.py": 'import os\n\nA = os.getenv("A")\nB = os.getenv("B")\n'})[1]
    assert "CFG-REQUIRED-ENV-AT-IMPORT" not in {x["rule"] for x in r["findings"]}


# ------------------------------------------------------------------ 4b. line counts ignore the trailing newline
def test_line_count_does_not_count_the_empty_string_after_the_final_newline():
    res = read_archive(iter([make_tarball({"a.py": "x = 1\ny = 2\n", "b.py": "x = 1\ny = 2", "c.py": "", "README.md": "# T\n\ntext\n"})]), Limits())
    n = {e.path: e.line_count for e in res.entries}
    assert (n["a.py"], n["b.py"], n["c.py"], n["README.md"]) == (2, 2, 0, 3)
    assert extract_facts("x = 1\ny = 2\n", "a.py")["line_count"] == 2 and extract_facts("x = 1", "b.py")["line_count"] == 1
    assert extract_web_facts("a.js", "const a = 1;\n")["line_count"] == 1


def test_module_spans_and_size_thresholds_use_the_real_line_count():
    twenty = "".join(f"x{i} = {i}\n" for i in range(20))
    g = analyze({"app/__init__.py": "", "app/m.py": twenty})[0]
    mod = next(n for n in g.nodes if n.type == "module" and n.path == "app/m.py")
    assert mod.end == 20


# ------------------------------------------------------------------ 5. auth recognition in SEC-UNAUTH-MUTATION (exposed by fix 1)
AUTH_DEPS = '''from typing import Annotated

from fastapi import Depends


def get_current_user():
    return 1


def get_current_active_superuser(user: Annotated[int, Depends(get_current_user)]):
    return user


CurrentUser = Annotated[int, Depends(get_current_user)]
'''
AUTH_MAIN = '''from fastapi import Depends, FastAPI

from app.deps import CurrentUser, get_current_active_superuser

app = FastAPI()


@app.post("/items")
def create(current_user: CurrentUser):
    return 1


@app.delete("/items/{i}", dependencies=[Depends(get_current_active_superuser)])
def remove(i: int):
    return i


@app.post("/signup")
def signup():
    return 1
'''


def test_annotated_alias_and_superuser_dependencies_count_as_auth():
    g, r, _, _ = analyze({"app/__init__.py": "", "app/deps.py": AUTH_DEPS, "app/main.py": AUTH_MAIN})
    deps = {n.meta["full_path"]: n.meta["dependencies"] for n in g.nodes if n.type == "route"}
    assert deps["/items"] == ["get_current_user"]  # resolved through the CurrentUser alias defined in app/deps.py
    assert deps["/items/{i}"] == ["get_current_active_superuser"]
    rules = {x["rule"]: x for x in r["findings"]}
    assert "SEC-NO-AUTH-DETECTED" not in rules
    assert [e["note"] for e in rules["SEC-UNAUTH-MUTATION"]["evidence"]] == ["POST /signup"]


def test_alias_without_depends_is_not_treated_as_a_dependency():
    main = AUTH_MAIN.replace("from app.deps import CurrentUser, get_current_active_superuser", "from app.deps import get_current_active_superuser\n\nUserId = int").replace("current_user: CurrentUser", "current_user: UserId")
    g = analyze({"app/__init__.py": "", "app/deps.py": AUTH_DEPS, "app/main.py": main})[0]
    assert {n.meta["full_path"]: n.meta["dependencies"] for n in g.nodes if n.type == "route"}["/items"] == []
