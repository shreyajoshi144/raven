"""Sprint 1: commit-aware answers, incremental indexing, hybrid retrieval channels, tenant isolation, consistency after failures."""
import logging
import uuid

import pytest
from sqlalchemy import func, select

from app.core.db import new_session
from app.models import AnalysisFile, AnalysisJob, ChatMessage, CodeEdge, CodeNode
from app.retrieval.search import CHANNELS, retrieve
from app.services.incremental import diff_files
from app.workers import stages
from tests.conftest import create_analysis, emulate_n8n, new_other_client
from tests.fakes import FakeLLM
from tests.test_chat import ask, wire

SHA2, SHA3 = "c" * 40, "d" * 40
V1 = {"app/__init__.py": "", "app/main.py": "from app.billing import charge\n\n\ndef checkout(order):\n    return charge(order)\n",
      "app/billing.py": '"""Billing."""\n\n\ndef charge(order):\n    return order\n', "app/old.py": "def legacy():\n    return 1\n",
      "app/util.py": "def helper():\n    return 2\n"}
V2 = {**{k: v for k, v in V1.items() if k not in ("app/old.py", "app/util.py")},
      "app/billing.py": '"""Billing."""\n\n\ndef charge(order):\n    return order * 2\n\n\ndef refund(order):\n    return -order\n',
      "app/helpers.py": "def helper():\n    return 2\n", "app/new.py": "def fresh():\n    return 3\n"}  # util.py renamed to helpers.py


def run(client, gh, files, sha):
    gh.files, gh.sha, gh._tar = files, sha, None
    r = create_analysis(client)
    aid = r.json()["analysis_id"]
    emulate_n8n(client, aid, gh, FakeLLM(), exec_id=f"e{sha[:4]}")
    return aid


def counts(aid):
    with new_session() as db:
        i = uuid.UUID(aid)
        return (db.execute(select(func.count()).select_from(CodeNode).where(CodeNode.analysis_id == i)).scalar_one(),
                db.execute(select(func.count()).select_from(CodeEdge).where(CodeEdge.analysis_id == i)).scalar_one(),
                db.execute(select(func.count(func.distinct(CodeNode.node_key))).where(CodeNode.analysis_id == i)).scalar_one(),
                db.execute(select(func.count(func.distinct(CodeEdge.edge_key))).where(CodeEdge.analysis_id == i)).scalar_one())


def summary(aid):
    with new_session() as db:
        return dict(db.get(AnalysisJob, uuid.UUID(aid)).summary)


def test_diff_detects_added_modified_deleted_renamed():
    d = diff_files({"a": "1", "b": "2", "c": "3", "d": "4"}, {"a": "1", "b": "9", "e": "3", "f": "5"})
    assert d == {"added": ["f"], "modified": ["b"], "deleted": ["d"], "renamed": [{"from": "c", "to": "e"}], "unchanged": 1}


def test_incremental_indexing_across_commits(user_client, gh_fake):
    a1 = run(user_client, gh_fake, V1, "b" * 40)
    assert summary(a1)["incremental"]["mode"] == "full"
    a2 = run(user_client, gh_fake, V2, SHA2)
    inc = summary(a2)["incremental"]
    assert inc["mode"] == "incremental" and inc["base_analysis_id"] == a1 and inc["base_commit"] == "b" * 40
    assert inc["added"] == ["app/new.py"] and inc["modified"] == ["app/billing.py"] and inc["deleted"] == ["app/old.py"]
    assert inc["renamed"] == [{"from": "app/util.py", "to": "app/helpers.py"}]
    p = summary(a2)["parse"]
    assert p["reused_from_base"] >= 2 and p["reparsed"] < p["parsed"] + 1 + 3  # __init__ + main reused; billing/helpers/new reparsed
    assert p["reused_from_base"] + p["reparsed"] == 5
    # the incremental graph is identical to a from-scratch graph of the same commit, with no duplicate keys
    inc_counts = counts(a2)
    assert inc_counts[0] == inc_counts[2] and inc_counts[1] == inc_counts[3]
    assert user_client.post(f"/api/v1/analyses/{a2}/reindex", headers={"Origin": "http://testserver"}).status_code == 202
    emulate_n8n(user_client, a2, gh_fake, FakeLLM(), exec_id="reidx")
    s = summary(a2)
    assert s["incremental"]["mode"] == "full" and s["parse"]["reused_from_base"] == 0
    assert counts(a2) == inc_counts
    with new_session() as db:
        names = {n for (n,) in db.execute(select(CodeNode.name).where(CodeNode.analysis_id == uuid.UUID(a2)))}
    assert {"refund", "fresh", "helper"} <= names and "legacy" not in names
    # history: the old commit's evidence is untouched by the new commit
    with new_session() as db:
        old = {n for (n,) in db.execute(select(CodeNode.name).where(CodeNode.analysis_id == uuid.UUID(a1)))}
        assert {"legacy", "helper"} <= old and "refund" not in old
        assert db.get(AnalysisJob, uuid.UUID(a1)).commit_sha == "b" * 40


def test_repeated_submission_creates_no_duplicates(user_client, gh_fake):
    a = run(user_client, gh_fake, V1, "b" * 40)
    before = counts(a)
    again = create_analysis(user_client).json()
    assert again["analysis_id"] == a and again["reused"] is True
    assert counts(a) == before


def test_answers_and_findings_record_their_commit(user_client, gh_fake, orch, monkeypatch):
    llm = FakeLLM()
    wire(orch, user_client, llm, monkeypatch)
    a1 = run(user_client, gh_fake, V1, "b" * 40)
    a2 = run(user_client, gh_fake, V2, SHA2)
    for aid, sha in ((a1, "b" * 40), (a2, SHA2)):
        ans = ask(user_client, aid, "what does charge do in app/billing.py?").json()["answer"]
        assert ans["commit_sha"] == sha
        assert all(c["commit_sha"] == sha for c in ans["citations"])
        rd = user_client.get(f"/api/v1/analyses/{aid}/readiness").json()
        assert rd["commit_sha"] == sha and all(f["commit_sha"] == sha for f in rd["findings"])
        hist = user_client.get(f"/api/v1/analyses/{aid}/chat").json()
        assert {m["commit_sha"] for m in hist["items"]} == {sha}
    with new_session() as db:  # new commits never rewrote the old answers
        assert {c for (c,) in db.execute(select(ChatMessage.commit_sha).where(ChatMessage.analysis_id == uuid.UUID(a1)))} == {"b" * 40}


def test_retrieval_channels_work_independently_and_carry_provenance(user_client, gh_fake):
    a = run(user_client, gh_fake, V1, "b" * 40)
    with new_session() as db:
        lex = retrieve(db, uuid.UUID(a), "how does checkout call charge?", channels=frozenset({"lexical"}))
        gr = retrieve(db, uuid.UUID(a), "how does checkout call charge?", channels=frozenset({"graph"}))
        allc = retrieve(db, uuid.UUID(a), "how does checkout call charge?")
        none = retrieve(db, uuid.UUID(a), "how does checkout call charge?", channels=frozenset())
    assert lex and all(e["channel"] == "lexical" for e in lex)
    assert gr and all(e["channel"] == "graph" for e in gr)
    assert none == [] and CHANNELS == {"lexical", "semantic", "graph"}
    assert {e["channel"] for e in allc} >= {"lexical"} and all(e["commit_sha"] == "b" * 40 for e in allc)
    assert any(e["symbol"] and e["symbol"].endswith("charge") for e in allc)


def test_cross_tenant_access_is_denied_everywhere(app, user_client, gh_fake):
    a = run(user_client, gh_fake, V1, "b" * 40)
    other = new_other_client(app, "intruder@example.com")
    hdr = {"Origin": "http://testserver"}
    for method, path in [("get", ""), ("get", "/graph"), ("get", "/files"), ("get", "/readiness"), ("get", "/impact"), ("get", "/docs"),
                         ("get", "/chat"), ("delete", "/chat"), ("post", "/reindex"), ("post", "/retry"), ("post", "/cancel")]:
        r = getattr(other, method)(f"/api/v1/analyses/{a}{path}", **({"headers": hdr} if method != "get" else {}))
        assert r.status_code == 404, (method, path, r.status_code)
    assert other.post(f"/api/v1/analyses/{a}/chat", json={"message": "charge?"}, headers=hdr).status_code == 404
    assert other.get("/api/v1/analyses").json()["items"] == []
    with new_session() as db:
        f = db.execute(select(AnalysisFile.id).where(AnalysisFile.analysis_id == uuid.UUID(a)).limit(1)).scalar_one()
    assert other.get(f"/api/v1/analyses/{a}/files/{f}").status_code == 404


def test_incremental_base_is_never_another_users_analysis(app, user_client, gh_fake):
    run(user_client, gh_fake, V1, "b" * 40)
    other = new_other_client(app, "second@example.com")
    gh_fake.files, gh_fake.sha, gh_fake._tar = V2, SHA2, None
    aid = create_analysis(other).json()["analysis_id"]
    emulate_n8n(other, aid, gh_fake, FakeLLM(), exec_id="oth")
    inc = summary(aid)["incremental"]
    assert inc["mode"] == "full" and inc["base_analysis_id"] is None


def test_failed_reindex_leaves_previous_graph_intact(user_client, gh_fake, monkeypatch):
    a = run(user_client, gh_fake, V1, "b" * 40)
    before = counts(a)
    real, n = stages._node_row, {"i": 0}

    def boom(job_id, node):
        n["i"] += 1
        if n["i"] > 2:
            raise RuntimeError("disk full")
        return real(job_id, node)
    monkeypatch.setattr(stages, "_node_row", boom)
    from app.core.config import get_settings
    import time
    with pytest.raises(RuntimeError):
        stages.stage_graph(uuid.UUID(a), get_settings(), time.monotonic() + 60)
    assert counts(a) == before  # delete + insert are one transaction: nothing half-written


def test_no_llm_no_embeddings_still_analyzes_retrieves_and_labels_answers(user_client, gh_fake, orch, monkeypatch, caplog):
    wire(orch, user_client, None, monkeypatch)
    from app.core.errors import JobError
    from app.services import qa as qasvc

    def dead(s):
        raise JobError("LLM_NOT_CONFIGURED")
    monkeypatch.setattr(qasvc, "build_provider", dead)
    canary = "SECRET_CANARY_xyz"
    files = {**V1, "app/billing.py": f'"""Billing."""\n\nCANARY = "{canary}"\n\n\ndef charge(order):\n    return order\n'}
    a = run(user_client, gh_fake, files, "b" * 40)
    assert summary(a)["graph"]["node_count"] > 0 and summary(a)["readiness"]
    with caplog.at_level(logging.DEBUG):
        ans = ask(user_client, a, "what does charge do?").json()["answer"]
    assert ans["answer_source"] == "retrieval_only" and ans["citations"] and ans["commit_sha"] == "b" * 40
    assert canary not in caplog.text
