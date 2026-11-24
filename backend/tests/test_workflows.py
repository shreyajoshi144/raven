"""Static validation of the three n8n workflows: generated JSON is in sync, the graph is well-formed, secrets are never embedded."""
import importlib.util
import json
import re
from pathlib import Path

import pytest

N8N = Path(__file__).resolve().parents[2] / "automation" / "n8n"
NAMES = {"raven_repository_analysis": "raven-analysis", "raven_documentation_generation": "raven-docs", "raven_codebase_qa": "raven-qa"}


def load(name):
    return json.loads((N8N / f"{name}.json").read_text())


def test_generator_output_matches_committed_json():
    spec = importlib.util.spec_from_file_location("build_workflows", N8N / "build_workflows.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for fn, name in ((mod.analysis_workflow, "raven_repository_analysis"), (mod.docs_workflow, "raven_documentation_generation"), (mod.qa_workflow, "raven_codebase_qa")):
        assert json.dumps(fn(), indent=2) + "\n" == (N8N / f"{name}.json").read_text(), f"{name}.json is stale: run automation/n8n/build_workflows.py"


@pytest.mark.parametrize("name", NAMES)
def test_workflow_graph_is_well_formed(name):
    d = load(name)
    assert d["id"] == name and d["name"] and d["settings"]["executionOrder"] == "v1"
    names = [n["name"] for n in d["nodes"]]
    assert len(names) == len(set(names)) and len({n["id"] for n in d["nodes"]}) == len(names)
    for n in d["nodes"]:
        assert n["type"].startswith("n8n-nodes-base.") and isinstance(n["typeVersion"], (int, float)) and len(n["position"]) == 2
    hooks = [n for n in d["nodes"] if n["type"] == "n8n-nodes-base.webhook"]
    assert len(hooks) == 1 and hooks[0]["parameters"]["path"] == NAMES[name] and hooks[0]["parameters"]["httpMethod"] == "POST"
    assert hooks[0]["parameters"]["responseMode"] == "responseNode" and hooks[0]["webhookId"]
    assert any(n["type"] == "n8n-nodes-base.respondToWebhook" for n in d["nodes"])
    reached, targets = {hooks[0]["name"]}, set()
    for src, outs in d["connections"].items():
        assert src in names, f"connection from unknown node {src}"
        for branch in outs["main"]:
            for c in branch:
                assert c["node"] in names and c["type"] == "main", (src, c)
                targets.add(c["node"])
    frontier = [hooks[0]["name"]]
    while frontier:
        cur = frontier.pop()
        for branch in d["connections"].get(cur, {}).get("main", []):
            for c in branch:
                if c["node"] not in reached:
                    reached.add(c["node"])
                    frontier.append(c["node"])
    assert reached == set(names), f"unreachable nodes: {set(names) - reached}"


@pytest.mark.parametrize("name", NAMES)
def test_workflows_call_only_internal_api_and_embed_no_secrets(name):
    raw = (N8N / f"{name}.json").read_text()
    d = json.loads(raw)
    for n in d["nodes"]:
        if n["type"] == "n8n-nodes-base.httpRequest":
            url = n["parameters"]["url"]
            hdrs = {h["name"]: h["value"] for h in n["parameters"].get("headerParameters", {}).get("parameters", [])}
            assert all(v.startswith("={{") and "$env." in v for v in hdrs.values()), (n["name"], "header values must come from the n8n environment")
            if "/webhook/" in url:                                       # analysis -> documentation workflow hand-off only
                assert name == "raven_repository_analysis" and url.endswith("/webhook/raven-docs' }}") and "X-Raven-Webhook-Secret" in hdrs, n["name"]
            else:
                assert "/internal/v1/" in url and hdrs.get("X-Internal-Secret") == "={{ $env.INTERNAL_SERVICE_SECRET }}", n["name"]
    assert not re.search(r"(sk-ant-|ghp_|github_pat_|AKIA[0-9A-Z]{16}|-----BEGIN|raven_dev_pw)", raw)
