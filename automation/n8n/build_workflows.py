#!/usr/bin/env python3
"""Generates the importable n8n workflow JSON files. Run: python build_workflows.py

Design: n8n only orchestrates. It calls authenticated /internal/v1 endpoints; the backend owns every state
transition. Secrets are read from n8n environment variables at runtime and are never embedded in the JSON.
"""
import json
import uuid
from pathlib import Path

HERE = Path(__file__).parent
NS = uuid.UUID("6f1c2a52-0000-4000-8000-000000000000")


def nid(name: str) -> str:
    return str(uuid.uuid5(NS, name))


class WF:
    def __init__(self, wf_id: str, name: str):
        self.id, self.name = wf_id, name
        self.nodes: list[dict] = []
        self.conns: dict = {}
        self.x = 0

    def add(self, name, type_, params, version=1, pos=None, **extra):
        node = {"parameters": params, "id": nid(self.id + name), "name": name, "type": type_, "typeVersion": version,
                "position": pos or [self.x, 300]}
        node.update(extra)
        self.nodes.append(node)
        return name

    def connect(self, src, dst, output=0):
        outs = self.conns.setdefault(src, {"main": []})["main"]
        while len(outs) <= output:
            outs.append([])
        outs[output].append({"node": dst, "type": "main", "index": 0})

    def export(self):
        return {"id": self.id, "name": self.name, "nodes": self.nodes, "connections": self.conns, "active": False,
                "settings": {"executionOrder": "v1", "saveManualExecutions": True, "saveDataErrorExecution": "all",
                             "saveDataSuccessExecution": "all", "executionTimeout": 3600, "timezone": "UTC"},
                "pinData": {}, "meta": {"templateCredsSetupCompleted": True, "instanceId": "raven"}, "tags": [], "versionId": nid(self.id + "v1")}


def webhook(wf, path, pos, response_mode="responseNode"):
    return wf.add("Webhook", "n8n-nodes-base.webhook", {"httpMethod": "POST", "path": path, "responseMode": response_mode, "options": {}},
                  version=2, pos=pos, webhookId=nid(wf.id + "webhook"))


def code(wf, name, js, pos):
    return wf.add(name, "n8n-nodes-base.code", {"jsCode": js}, version=2, pos=pos)


def if_bool(wf, name, expr, pos):
    return wf.add(name, "n8n-nodes-base.if", {"conditions": {"options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict", "version": 2},
                  "conditions": [{"id": nid(wf.id + name + "c"), "leftValue": expr, "rightValue": "", "operator": {"type": "boolean", "operation": "true", "singleValue": True}}],
                  "combinator": "and"}, "options": {}}, version=2.2, pos=pos)


def switch(wf, name, keys, pos, field="next"):
    rules = [{"conditions": {"options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict", "version": 2},
              "conditions": [{"id": nid(wf.id + name + k), "leftValue": "={{ $json." + field + " }}", "rightValue": k,
                              "operator": {"type": "string", "operation": "equals"}}], "combinator": "and"},
              "renameOutput": True, "outputKey": k} for k in keys]
    return wf.add(name, "n8n-nodes-base.switch", {"rules": {"values": rules}, "options": {}}, version=3.2, pos=pos)


def http(wf, name, method, url_expr, body_expr, pos, timeout=20000, headers=None):
    hdrs = headers or [{"name": "X-Internal-Secret", "value": "={{ $env.INTERNAL_SERVICE_SECRET }}"}]
    params = {"method": method, "url": url_expr, "sendHeaders": True, "headerParameters": {"parameters": hdrs},
              "options": {"timeout": timeout, "response": {"response": {"fullResponse": True, "neverError": True, "responseFormat": "json"}}}}
    if body_expr:
        params.update({"sendBody": True, "specifyBody": "json", "jsonBody": body_expr})
    return wf.add(name, "n8n-nodes-base.httpRequest", params, version=4.2, pos=pos, onError="continueRegularOutput")


def wait(wf, name, seconds_expr, pos):
    return wf.add(name, "n8n-nodes-base.wait", {"resume": "timeInterval", "amount": seconds_expr, "unit": "seconds"}, version=1.1, pos=pos,
                  webhookId=nid(wf.id + name))


def respond(wf, name, code_, body_expr, pos):
    return wf.add(name, "n8n-nodes-base.respondToWebhook", {"respondWith": "json", "responseBody": body_expr, "options": {"responseCode": code_}}, version=1.1, pos=pos)


EQ = "function eq(a,b){if(typeof a!=='string'||typeof b!=='string'||a.length!==b.length)return false;let r=0;for(let i=0;i<a.length;i++)r|=a.charCodeAt(i)^b.charCodeAt(i);return r===0;}"
API = "$env.RAVEN_API_BASE_URL"
FAIL_CODES = "'WORKFLOW_TIMEOUT'|'WORKFLOW_FAILED'|'ORCHESTRATOR_UNAVAILABLE'"


def init_code(extra_fields: str, id_fields=("analysis_id",)):
    checks = " && ".join(f"UUID.test(String(body.{f} || ''))" for f in id_fields)
    fields = ", ".join(f"{f}: body.{f}" for f in id_fields)
    return f"""{EQ}
const UUID = /^[0-9a-fA-F]{{8}}-[0-9a-fA-F]{{4}}-[0-9a-fA-F]{{4}}-[0-9a-fA-F]{{4}}-[0-9a-fA-F]{{12}}$/;
const req = $input.first().json;
const body = req.body || {{}};
const secret = $env.RAVEN_N8N_WEBHOOK_SECRET || $env.N8N_WEBHOOK_SECRET;
const authorized = eq(String((req.headers || {{}})['x-raven-webhook-secret'] || ''), String(secret || '')) && !!secret;
const valid = {checks};
return [{{ json: {{ authorized: authorized && valid, state: {{ {fields}, execId: String($execution.id), {extra_fields} }} }} }}];"""


def pump(state_js="s"):
    return "return [{ json: { state: " + state_js + ", req: req } }];"


# ----------------------------------------------------------------------------------------------
def analysis_workflow():
    wf = WF("raven_repository_analysis", "Raven - Repository Analysis")
    webhook(wf, "raven-analysis", [0, 300])
    code(wf, "Init", init_code("dispatchTries: 0, polls: 0, triggerTries: 0, attempt: 0"), [240, 300])
    if_bool(wf, "Authorized?", "={{ $json.authorized }}", [480, 300])
    respond(wf, "Respond Accepted", 202, '={{ JSON.stringify({ accepted: true, execution_id: $execution.id }) }}', [720, 200])
    respond(wf, "Respond Unauthorized", 401, '={{ JSON.stringify({ error: "unauthorized" }) }}', [720, 460])
    code(wf, "Prepare Dispatch", f"""const s = $input.first().json.state || $('Init').first().json.state;
const key = s.execId + ':dispatch:' + s.attempt + ':' + s.dispatchTries;
return [{{ json: {{ state: s, req: {{ kind: 'analysis', workflow: 'raven_repository_analysis', execution_id: s.execId, idempotency_key: key }} }} }}];""", [960, 300])
    http(wf, "Dispatch", "POST", "={{ " + API + " + '/internal/v1/analysis-jobs/' + $json.state.analysis_id + '/dispatch' }}", "={{ JSON.stringify($json.req) }}", [1200, 300])
    code(wf, "Eval Dispatch", """const prev = $('Prepare Dispatch').last().json.state;
const r = $input.first().json;
const s = { ...prev };
const status = r.statusCode;
if (status === 200) return [{ json: { state: s, next: 'ok' } }];
if (status === 409 || status === 404 || status === 401 || status === 422) return [{ json: { state: s, next: 'stop', reason: 'dispatch rejected: ' + status } }];
s.dispatchTries = (s.dispatchTries || 0) + 1;
if (s.dispatchTries >= 4) return [{ json: { state: s, next: 'fail', code: 'WORKFLOW_FAILED', stage: 'dispatch' } }];
return [{ json: { state: s, next: 'retry', waitSeconds: Math.min(30, 2 ** s.dispatchTries * 2) } }];""", [1440, 300])
    switch(wf, "Route Dispatch", ["ok", "retry", "stop", "fail"], [1680, 300])
    wait(wf, "Wait Dispatch Retry", "={{ $json.waitSeconds }}", [1920, 460])
    wait(wf, "Wait Before Poll", 4, [1920, 120])
    code(wf, "Prepare Poll", "const s = { ...$input.first().json.state }; s.polls = (s.polls || 0) + 1;\n" + "return [{ json: { state: s } }];", [2160, 120])
    http(wf, "Poll Status", "GET", "={{ " + API + " + '/internal/v1/analysis-jobs/' + $json.state.analysis_id + '/status' }}", None, [2400, 120])
    code(wf, "Eval Status", """const s = { ...$('Prepare Poll').last().json.state };
const r = $input.first().json;
const maxPolls = Math.ceil(((Number($env.RAVEN_MAX_ANALYSIS_SECONDS) || 600) + 120) / 4);
if (r.statusCode !== 200 || !r.body) {
  s.errors = (s.errors || 0) + 1;
  if (s.errors > 8) return [{ json: { state: s, next: 'fail', code: 'WORKFLOW_FAILED', stage: 'poll' } }];
  return [{ json: { state: s, next: 'working' } }];
}
const b = r.body;
s.errors = 0;
if (b.state === 'FAILED' || b.state === 'CANCELLED' || b.state === 'READY') return [{ json: { state: s, next: 'stop', reason: 'job is ' + b.state } }];
if (b.state === 'RETRYING') { s.attempt = b.attempt + 1; s.dispatchTries = 0; return [{ json: { state: s, next: 'retrying', waitSeconds: Math.max(1, Math.ceil(b.retry_in_seconds || 1)) } }]; }
if (b.state === 'BUILDING_GRAPH' && b.graph_complete) return [{ json: { state: s, next: 'graph_ready' } }];
if (b.state === 'GENERATING_DOCS') return [{ json: { state: s, next: 'graph_ready' } }];
if (s.polls >= maxPolls) return [{ json: { state: s, next: 'fail', code: 'WORKFLOW_TIMEOUT', stage: 'poll' } }];
return [{ json: { state: s, next: 'working' } }];""", [2640, 120])
    switch(wf, "Route Status", ["working", "retrying", "graph_ready", "stop", "fail"], [2880, 120])
    wait(wf, "Wait Backoff", "={{ $json.waitSeconds }}", [3120, 300])
    code(wf, "Prepare Stage Result", """const s = $input.first().json.state;
return [{ json: { state: s, req: { stage: 'graph', workflow: 'raven_repository_analysis', execution_id: s.execId, idempotency_key: s.execId + ':graph' } } }];""", [3120, 0])
    http(wf, "Stage Result", "POST", "={{ " + API + " + '/internal/v1/analysis-jobs/' + $json.state.analysis_id + '/stage-result' }}", "={{ JSON.stringify($json.req) }}", [3360, 0])
    code(wf, "Eval Stage Result", """const s = { ...$('Prepare Stage Result').last().json.state };
const r = $input.first().json;
if (r.statusCode === 200 && r.body && r.body.doc_id) { s.doc_id = r.body.doc_id; return [{ json: { state: s, next: 'ok' } }]; }
if (r.statusCode === 409) return [{ json: { state: s, next: 'stop', reason: 'stage-result rejected' } }];
s.stageTries = (s.stageTries || 0) + 1;
if (s.stageTries >= 4) return [{ json: { state: s, next: 'fail', code: 'WORKFLOW_FAILED', stage: 'stage-result' } }];
return [{ json: { state: s, next: 'retry', waitSeconds: 3 } }];""", [3600, 0])
    switch(wf, "Route Stage Result", ["ok", "retry", "stop", "fail"], [3840, 0])
    wait(wf, "Wait Stage Retry", "={{ $json.waitSeconds }}", [4080, 140])
    code(wf, "Prepare Docs Trigger", """const s = { ...$input.first().json.state };
s.triggerTries = (s.triggerTries || 0) + 1;
return [{ json: { state: s, req: { analysis_id: s.analysis_id, doc_id: s.doc_id } } }];""", [4080, -120])
    http(wf, "Trigger Docs Workflow", "POST", "={{ ($env.N8N_SELF_URL || 'http://localhost:5678') + '/webhook/raven-docs' }}", "={{ JSON.stringify($json.req) }}", [4320, -120],
         headers=[{"name": "X-Raven-Webhook-Secret", "value": "={{ $env.RAVEN_N8N_WEBHOOK_SECRET || $env.N8N_WEBHOOK_SECRET }}"}])
    code(wf, "Eval Docs Trigger", """const s = { ...$('Prepare Docs Trigger').last().json.state };
const r = $input.first().json;
if (r.statusCode >= 200 && r.statusCode < 300) return [{ json: { state: s, next: 'ok' } }];
if (s.triggerTries >= 4) return [{ json: { state: s, next: 'fail', code: 'WORKFLOW_FAILED', stage: 'trigger-docs' } }];
return [{ json: { state: s, next: 'retry', waitSeconds: 3 * s.triggerTries } }];""", [4560, -120])
    switch(wf, "Route Docs Trigger", ["ok", "retry", "fail"], [4800, -120], field="next")
    wait(wf, "Wait Trigger Retry", "={{ $json.waitSeconds }}", [5040, 20])
    code(wf, "Prepare Failure", """const j = $input.first().json;
const s = j.state;
return [{ json: { state: s, req: { error_code: j.code || 'WORKFLOW_FAILED', stage: j.stage || 'workflow', workflow: 'raven_repository_analysis', execution_id: s.execId, idempotency_key: s.execId + ':fail:' + (j.stage || 'x') } } }];""", [3120, 700])
    http(wf, "Report Failure", "POST", "={{ " + API + " + '/internal/v1/analysis-jobs/' + $json.state.analysis_id + '/fail' }}", "={{ JSON.stringify($json.req) }}", [3360, 700])
    wf.add("Done", "n8n-nodes-base.noOp", {}, pos=[5280, 300])
    wf.add("Stopped", "n8n-nodes-base.noOp", {}, pos=[3360, 460])

    c = wf.connect
    c("Webhook", "Init"); c("Init", "Authorized?")
    c("Authorized?", "Respond Accepted", 0); c("Authorized?", "Prepare Dispatch", 0); c("Authorized?", "Respond Unauthorized", 1)
    c("Prepare Dispatch", "Dispatch"); c("Dispatch", "Eval Dispatch"); c("Eval Dispatch", "Route Dispatch")
    c("Route Dispatch", "Wait Before Poll", 0); c("Route Dispatch", "Wait Dispatch Retry", 1); c("Route Dispatch", "Stopped", 2); c("Route Dispatch", "Prepare Failure", 3)
    c("Wait Dispatch Retry", "Prepare Dispatch")
    c("Wait Before Poll", "Prepare Poll"); c("Prepare Poll", "Poll Status"); c("Poll Status", "Eval Status"); c("Eval Status", "Route Status")
    c("Route Status", "Wait Before Poll", 0); c("Route Status", "Wait Backoff", 1); c("Route Status", "Prepare Stage Result", 2)
    c("Route Status", "Stopped", 3); c("Route Status", "Prepare Failure", 4)
    c("Wait Backoff", "Prepare Dispatch")
    c("Prepare Stage Result", "Stage Result"); c("Stage Result", "Eval Stage Result"); c("Eval Stage Result", "Route Stage Result")
    c("Route Stage Result", "Prepare Docs Trigger", 0); c("Route Stage Result", "Wait Stage Retry", 1); c("Route Stage Result", "Stopped", 2); c("Route Stage Result", "Prepare Failure", 3)
    c("Wait Stage Retry", "Prepare Stage Result")
    c("Prepare Docs Trigger", "Trigger Docs Workflow"); c("Trigger Docs Workflow", "Eval Docs Trigger"); c("Eval Docs Trigger", "Route Docs Trigger")
    c("Route Docs Trigger", "Done", 0); c("Route Docs Trigger", "Wait Trigger Retry", 1); c("Route Docs Trigger", "Prepare Failure", 2)
    c("Wait Trigger Retry", "Prepare Docs Trigger")
    c("Prepare Failure", "Report Failure"); c("Report Failure", "Done")
    return wf.export()


def docs_workflow():
    wf = WF("raven_documentation_generation", "Raven - Documentation Generation")
    webhook(wf, "raven-docs", [0, 300])
    code(wf, "Init", init_code("step: 'explain', dispatchTries: 0, polls: 0, attempt: 0", id_fields=("analysis_id", "doc_id")), [240, 300])
    if_bool(wf, "Authorized?", "={{ $json.authorized }}", [480, 300])
    respond(wf, "Respond Accepted", 202, '={{ JSON.stringify({ accepted: true, execution_id: $execution.id }) }}', [720, 200])
    respond(wf, "Respond Unauthorized", 401, '={{ JSON.stringify({ error: "unauthorized" }) }}', [720, 460])
    code(wf, "Prepare Dispatch", """const s = $input.first().json.state || $('Init').first().json.state;
const kind = s.step === 'explain' ? 'docs_explain' : 'docs_assemble';
const key = s.execId + ':' + kind + ':' + s.attempt + ':' + s.dispatchTries;
return [{ json: { state: s, req: { kind, workflow: 'raven_documentation_generation', execution_id: s.execId, doc_id: s.doc_id, idempotency_key: key } } }];""", [960, 300])
    http(wf, "Dispatch", "POST", "={{ " + API + " + '/internal/v1/analysis-jobs/' + $json.state.analysis_id + '/dispatch' }}", "={{ JSON.stringify($json.req) }}", [1200, 300])
    code(wf, "Eval Dispatch", """const s = { ...$('Prepare Dispatch').last().json.state };
const r = $input.first().json;
if (r.statusCode === 200) return [{ json: { state: s, next: 'ok' } }];
if ([401, 404, 409, 422].includes(r.statusCode)) return [{ json: { state: s, next: 'stop' } }];
s.dispatchTries = (s.dispatchTries || 0) + 1;
if (s.dispatchTries >= 4) return [{ json: { state: s, next: 'fail', code: 'WORKFLOW_FAILED', stage: 'dispatch-docs' } }];
return [{ json: { state: s, next: 'retry', waitSeconds: Math.min(30, 2 ** s.dispatchTries * 2) } }];""", [1440, 300])
    switch(wf, "Route Dispatch", ["ok", "retry", "stop", "fail"], [1680, 300])
    wait(wf, "Wait Dispatch Retry", "={{ $json.waitSeconds }}", [1920, 460])
    wait(wf, "Wait Before Poll", 3, [1920, 120])
    code(wf, "Prepare Poll", "const s = { ...$input.first().json.state }; s.polls = (s.polls || 0) + 1;\nreturn [{ json: { state: s } }];", [2160, 120])
    http(wf, "Poll Status", "GET", "={{ " + API + " + '/internal/v1/analysis-jobs/' + $json.state.analysis_id + '/status?doc_id=' + $json.state.doc_id }}", None, [2400, 120])
    code(wf, "Eval Status", """const s = { ...$('Prepare Poll').last().json.state };
const r = $input.first().json;
const maxPolls = Math.ceil(((Number($env.RAVEN_MAX_DOCS_SECONDS) || 900) + 60) / 3);
if (r.statusCode !== 200 || !r.body) {
  s.errors = (s.errors || 0) + 1;
  if (s.errors > 8) return [{ json: { state: s, next: 'fail', code: 'WORKFLOW_FAILED', stage: 'poll-docs' } }];
  return [{ json: { state: s, next: 'working' } }];
}
s.errors = 0;
const b = r.body;
const kind = s.step === 'explain' ? 'docs_explain' : 'docs_assemble';
const t = (b.doc_tasks || {})[kind];
if (b.state === 'FAILED' || b.state === 'CANCELLED') return [{ json: { state: s, next: 'stop' } }];
if (b.state === 'RETRYING') { s.attempt = (b.attempt || 0) + 1; s.dispatchTries = 0; return [{ json: { state: s, next: 'retrying', waitSeconds: Math.max(1, Math.ceil(b.retry_in_seconds || 1)) } }]; }
if (t === 'failed') return [{ json: { state: s, next: 'fail', code: 'WORKFLOW_FAILED', stage: kind } }];
if (t === 'done') {
  if (s.step === 'explain') { s.step = 'assemble'; s.polls = 0; s.dispatchTries = 0; return [{ json: { state: s, next: 'next_step' } }]; }
  if (b.docs && (b.docs.status === 'READY' || b.docs.status === 'PARTIAL')) return [{ json: { state: s, next: 'complete' } }];
}
if (s.polls >= maxPolls) return [{ json: { state: s, next: 'fail', code: 'WORKFLOW_TIMEOUT', stage: kind } }];
return [{ json: { state: s, next: 'working' } }];""", [2640, 120])
    switch(wf, "Route Status", ["working", "retrying", "next_step", "complete", "stop", "fail"], [2880, 120])
    wait(wf, "Wait Backoff", "={{ $json.waitSeconds }}", [3120, 300])
    code(wf, "Prepare Complete", """const s = $input.first().json.state;
return [{ json: { state: s, req: { doc_id: s.doc_id, workflow: 'raven_documentation_generation', execution_id: s.execId, idempotency_key: s.execId + ':complete' } } }];""", [3120, 0])
    http(wf, "Complete", "POST", "={{ " + API + " + '/internal/v1/analysis-jobs/' + $json.state.analysis_id + '/complete' }}", "={{ JSON.stringify($json.req) }}", [3360, 0])
    code(wf, "Eval Complete", """const s = { ...$('Prepare Complete').last().json.state };
const r = $input.first().json;
if (r.statusCode === 200) return [{ json: { state: s, next: 'ok' } }];
s.completeTries = (s.completeTries || 0) + 1;
if (r.statusCode === 409 || s.completeTries >= 4) return [{ json: { state: s, next: 'fail', code: 'WORKFLOW_FAILED', stage: 'complete' } }];
return [{ json: { state: s, next: 'retry', waitSeconds: 3 } }];""", [3600, 0])
    switch(wf, "Route Complete", ["ok", "retry", "fail"], [3840, 0])
    wait(wf, "Wait Complete Retry", "={{ $json.waitSeconds }}", [4080, 100])
    code(wf, "Prepare Failure", """const j = $input.first().json;
const s = j.state;
return [{ json: { state: s, req: { error_code: j.code || 'WORKFLOW_FAILED', stage: j.stage || 'docs', workflow: 'raven_documentation_generation', execution_id: s.execId, doc_id: s.doc_id, idempotency_key: s.execId + ':fail:' + (j.stage || 'x') } } }];""", [3120, 700])
    http(wf, "Report Failure", "POST", "={{ " + API + " + '/internal/v1/analysis-jobs/' + $json.state.analysis_id + '/fail' }}", "={{ JSON.stringify($json.req) }}", [3360, 700])
    wf.add("Done", "n8n-nodes-base.noOp", {}, pos=[4320, 300])
    wf.add("Stopped", "n8n-nodes-base.noOp", {}, pos=[3360, 460])
    c = wf.connect
    c("Webhook", "Init"); c("Init", "Authorized?")
    c("Authorized?", "Respond Accepted", 0); c("Authorized?", "Prepare Dispatch", 0); c("Authorized?", "Respond Unauthorized", 1)
    c("Prepare Dispatch", "Dispatch"); c("Dispatch", "Eval Dispatch"); c("Eval Dispatch", "Route Dispatch")
    c("Route Dispatch", "Wait Before Poll", 0); c("Route Dispatch", "Wait Dispatch Retry", 1); c("Route Dispatch", "Stopped", 2); c("Route Dispatch", "Prepare Failure", 3)
    c("Wait Dispatch Retry", "Prepare Dispatch")
    c("Wait Before Poll", "Prepare Poll"); c("Prepare Poll", "Poll Status"); c("Poll Status", "Eval Status"); c("Eval Status", "Route Status")
    c("Route Status", "Wait Before Poll", 0); c("Route Status", "Wait Backoff", 1); c("Route Status", "Prepare Dispatch", 2)
    c("Route Status", "Prepare Complete", 3); c("Route Status", "Stopped", 4); c("Route Status", "Prepare Failure", 5)
    c("Wait Backoff", "Prepare Dispatch")
    c("Prepare Complete", "Complete"); c("Complete", "Eval Complete"); c("Eval Complete", "Route Complete")
    c("Route Complete", "Done", 0); c("Route Complete", "Wait Complete Retry", 1); c("Route Complete", "Prepare Failure", 2)
    c("Wait Complete Retry", "Prepare Complete")
    c("Prepare Failure", "Report Failure"); c("Report Failure", "Done")
    return wf.export()


def qa_workflow():
    wf = WF("raven_codebase_qa", "Raven - Codebase Q&A")
    webhook(wf, "raven-qa", [0, 300])
    code(wf, "Init", init_code("", id_fields=("analysis_id", "message_id")), [240, 300])
    if_bool(wf, "Authorized?", "={{ $json.authorized }}", [480, 300])
    respond(wf, "Respond Unauthorized", 401, '={{ JSON.stringify({ error: { code: "UNAUTHENTICATED" } }) }}', [720, 460])
    code(wf, "Prepare Retrieve", "const s = $input.first().json.state;\nreturn [{ json: { state: s, req: { analysis_id: s.analysis_id, message_id: s.message_id, execution_id: s.execId } } }];", [720, 200])
    http(wf, "Retrieve Evidence", "POST", "={{ " + API + " + '/internal/v1/qa/retrieve' }}", "={{ JSON.stringify($json.req) }}", [960, 200], timeout=30000)
    code(wf, "Eval Retrieve", """const s = $('Prepare Retrieve').last().json.state;
const r = $input.first().json;
return [{ json: { state: s, ok: r.statusCode === 200, status: r.statusCode || 0 } }];""", [1200, 200])
    if_bool(wf, "Retrieve OK?", "={{ $json.ok }}", [1440, 200])
    code(wf, "Prepare Answer", "const s = $input.first().json.state;\nreturn [{ json: { state: s, req: { analysis_id: s.analysis_id, message_id: s.message_id, execution_id: s.execId } } }];", [1680, 120])
    http(wf, "Generate Answer", "POST", "={{ " + API + " + '/internal/v1/qa/answer' }}", "={{ JSON.stringify($json.req) }}", [1920, 120], timeout=110000)
    code(wf, "Eval Answer", """const s = $('Prepare Answer').last().json.state;
const r = $input.first().json;
return [{ json: { state: s, ok: r.statusCode === 200, status: r.statusCode || 0 } }];""", [2160, 120])
    if_bool(wf, "Answer OK?", "={{ $json.ok }}", [2400, 120])
    respond(wf, "Respond Answer", 200, '={{ JSON.stringify({ status: "complete", message_id: $json.state.message_id, execution_id: $json.state.execId }) }}', [2640, 40])
    respond(wf, "Respond Failure", 502, '={{ JSON.stringify({ error: { code: "WORKFLOW_FAILED", retryable: true } }) }}', [2640, 300])
    c = wf.connect
    c("Webhook", "Init"); c("Init", "Authorized?")
    c("Authorized?", "Prepare Retrieve", 0); c("Authorized?", "Respond Unauthorized", 1)
    c("Prepare Retrieve", "Retrieve Evidence"); c("Retrieve Evidence", "Eval Retrieve"); c("Eval Retrieve", "Retrieve OK?")
    c("Retrieve OK?", "Prepare Answer", 0); c("Retrieve OK?", "Respond Failure", 1)
    c("Prepare Answer", "Generate Answer"); c("Generate Answer", "Eval Answer"); c("Eval Answer", "Answer OK?")
    c("Answer OK?", "Respond Answer", 0); c("Answer OK?", "Respond Failure", 1)
    return wf.export()


if __name__ == "__main__":
    for fn, name in ((analysis_workflow, "raven_repository_analysis"), (docs_workflow, "raven_documentation_generation"), (qa_workflow, "raven_codebase_qa")):
        data = fn()
        (HERE / f"{name}.json").write_text(json.dumps(data, indent=2) + "\n")
        print("wrote", name, len(data["nodes"]), "nodes")
