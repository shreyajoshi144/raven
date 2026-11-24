"""Evidence-backed engineering-readiness report from static facts.

Principles (enforced in code, covered by tests):
  * Pattern findings (kind=observed|potential_risk) are emitted ONLY with at least one file:line evidence entry.
  * Absence findings (kind=absence) must state what was searched in `basis`.
  * Security findings are never "confirmed": exploitability is not assessed. `claim` always says what was and was not shown.
  * severity = impact IF the concern is real; confidence = how sure we are the pattern is what we say it is. They are independent.
  * No secret values are ever included - only file/line locations.
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from typing import Any

from app.analysis.graph import FileFacts, GraphResult, is_test_path

SEV = ["critical", "high", "medium", "low", "info"]
CONF = ["high", "medium", "low"]
CATEGORIES = ["testing", "error_handling", "security", "configuration", "logging", "maintainability"]
MAX_FINDINGS = 250
AUTH_NAME = re.compile(r"(auth|current_user|superuser|token|jwt|oauth|login|permission|security|api_key|credential|verify|require)", re.I)

DISCLAIMER = ("Static pattern analysis of the repository at the pinned commit. Nothing was executed and no tests were run. Findings are leads for human review: "
              "a security-category finding means a risky pattern was observed in the source, NOT that a vulnerability is confirmed or exploitable.")
NOT_ASSESSED = ["Runtime behaviour and exploitability", "Known-vulnerable dependency versions (no vulnerability database was consulted)", "Measured test coverage or test results",
                "Infrastructure, container and deployment configuration", "Correctness of authorization logic", "Business-logic flaws"]


def _ev(path: str, start: int, end: int | None = None, note: str | None = None) -> dict[str, Any]:
    return {"path": path, "start_line": max(1, start), "end_line": max(start, end or start, 1), **({"note": note} if note else {})}


class _Builder:
    def __init__(self) -> None:
        self.findings: list[dict[str, Any]] = []

    def add(self, rule: str, category: str, severity: str, confidence: str, kind: str, title: str, detail: str, recommendation: str, verify: str,
            evidence: list[dict[str, Any]], basis: str | None = None, count: int | None = None) -> None:
        if kind != "absence" and not evidence:
            return  # evidence is mandatory for pattern findings
        if kind == "absence" and not basis:
            return
        first = evidence[0] if evidence else {"path": "", "start_line": 0}
        fid = hashlib.sha1(f"{rule}|{first['path']}|{first['start_line']}".encode()).hexdigest()[:10]
        claim = {"observed": "This pattern is present in the source.", "potential_risk": "A risky pattern was observed. Whether it is exploitable or harmful was NOT verified.",
                 "absence": "Nothing matching was found in the analyzed files (see basis); it may exist elsewhere.", "coverage_gap": "No static link from any test file was found. Measured coverage was not collected.",
                 "metric": "A measured property of the code."}[kind]
        self.findings.append({"id": fid, "rule": rule, "category": category, "severity": severity, "confidence": confidence, "kind": kind, "title": title, "detail": detail,
                              "claim": claim, "recommendation": recommendation, "verify": verify, "evidence": evidence[:12], "evidence_total": count if count is not None else len(evidence),
                              **({"basis": basis} if basis else {})})


def _tarjan(adj: dict[str, list[str]]) -> list[list[str]]:
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on: set[str] = set()
    stack: list[str] = []
    out: list[list[str]] = []
    counter = 0
    for root in adj:
        if root in index:
            continue
        work = [(root, iter(adj.get(root, [])))]
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on.add(root)
        while work:
            v, it = work[-1]
            adv = False
            for w in it:
                if w not in index:
                    index[w] = low[w] = counter
                    counter += 1
                    stack.append(w)
                    on.add(w)
                    work.append((w, iter(adj.get(w, []))))
                    adv = True
                    break
                if w in on:
                    low[v] = min(low[v], index[w])
            if adv:
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[v])
            if low[v] == index[v]:
                comp = []
                while True:
                    w = stack.pop()
                    on.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                if len(comp) > 1:
                    out.append(comp)
    return out


RISK_RULES: dict[str, dict[str, Any]] = {
    "dynamic_code_exec": dict(rule="SEC-DYNAMIC-EXEC", severity="high", confidence="medium", title="Dynamic code execution (eval/exec) on a non-constant value",
        detail="eval()/exec() runs whatever string it receives. If any part can be influenced by a user, this allows arbitrary code execution.", rec="Replace with explicit parsing (e.g. ast.literal_eval, json) or a lookup table.", verify="Trace where the argument comes from; confirm it can never contain user-controlled text."),
    "os_system": dict(rule="SEC-SHELL-EXEC", severity="medium", confidence="medium", title="Shell command execution (os.system)", detail="Commands run through a shell are vulnerable to injection when any part is user-influenced.", rec="Use subprocess with an argument list and shell=False.", verify="Check whether the command string includes external input."),
    "subprocess_shell": dict(rule="SEC-SHELL-EXEC", severity="medium", confidence="medium", title="subprocess invoked with shell=True", detail="shell=True passes the command through a shell; injection is possible if any part is user-influenced.", rec="Pass an argument list and omit shell=True.", verify="Check whether the command includes external input."),
    "unsafe_deserialization": dict(rule="SEC-UNSAFE-DESERIALIZE", severity="high", confidence="medium", title="Unsafe deserialization (pickle/marshal/dill)", detail="Loading these formats from untrusted data can execute arbitrary code.", rec="Use a data-only format (JSON) or authenticate/sign the payload.", verify="Confirm the data source is trusted and integrity-protected."),
    "yaml_unsafe_load": dict(rule="SEC-YAML-LOAD", severity="medium", confidence="medium", title="yaml.load without an explicit safe Loader", detail="The default/unsafe loader can construct arbitrary Python objects.", rec="Use yaml.safe_load.", verify="Check what data reaches this call."),
    "weak_hash": dict(rule="SEC-WEAK-HASH", severity="low", confidence="low", title="MD5/SHA-1 used", detail="These hashes are unsuitable for passwords or signatures; they are fine for non-security checksums, which this static check cannot tell apart.", rec="Use SHA-256+ (or a password hash such as Argon2) where security matters.", verify="Determine whether the hash protects anything security-relevant."),
    "tls_verify_disabled": dict(rule="SEC-TLS-VERIFY-DISABLED", severity="high", confidence="high", title="TLS certificate verification explicitly disabled (verify=False)", detail="Disabling verification allows man-in-the-middle attacks on that connection.", rec="Remove verify=False; configure a trusted CA bundle instead.", verify="Check whether this code path runs outside local development."),
    "jwt_verify_disabled": dict(rule="SEC-JWT-VERIFY-DISABLED", severity="high", confidence="high", title="JWT signature verification explicitly disabled", detail="Tokens are accepted without checking their signature, so anyone can forge claims.", rec="Always verify signatures and pin the accepted algorithms.", verify="Confirm whether the decoded claims are ever trusted for authorization."),
    "sql_string_building": dict(rule="SEC-SQL-STRING-BUILD", severity="high", confidence="medium", title="SQL assembled with string formatting passed to execute()", detail="Interpolating values into SQL text enables SQL injection if any value is attacker-controlled.", rec="Use bound parameters (e.g. text('... :id'), {'id': value}).", verify="Check whether the interpolated values can come from requests."),
    "debug_enabled": dict(rule="SEC-DEBUG-MODE", severity="medium", confidence="medium", title="debug=True passed in code", detail="Debug mode can expose stack traces and interactive consoles.", rec="Drive debug from configuration and keep it off in production.", verify="Check whether this value is overridden per environment."),
}


def build_readiness(py: list[FileFacts], web: list[FileFacts], graph: GraphResult, support: dict[str, str], redactions: dict[str, list[int]],
                    partial: bool = False) -> dict[str, Any]:
    b = _Builder()
    pyf = [f for f in py if f.facts]
    prod = [f for f in pyf if not is_test_path(f.path)]
    tests = [f for f in pyf if is_test_path(f.path)]
    nodes = {n.key: n for n in graph.nodes}
    routes = graph.routes
    conf_cap = "medium" if partial else "high"  # absence claims are weaker when the analysis hit limits

    # ---------------------------------------------------------------- testing
    modules = [n for n in graph.nodes if n.type == "module" and not n.meta.get("web") and n.path and not n.path.endswith("__init__.py")]
    test_nodes = [n for n in graph.nodes if n.type == "test"]
    if not test_nodes and len(modules) >= 3:
        b.add("TEST-NONE", "testing", "high", conf_cap, "absence", "No test files found", f"{len(modules)} Python modules were analyzed and none are test files.",
              "Add automated tests, starting with the routes and core services.", "Search the repository for tests outside the analyzed paths.", [],
              basis=f"Looked for tests/ or test directories, test_*.py, *_test.py and conftest.py among {len(pyf)} analyzed Python files." + (" The analysis was partial." if partial else ""))
    elif test_nodes:
        adj: dict[str, list[str]] = defaultdict(list)
        for e in graph.edges:
            if e.relation == "imports" and e.resolution != "unresolved" and e.source in nodes and e.target in nodes and nodes[e.target].type in ("module", "test") and not nodes[e.target].meta.get("web"):
                adj[e.source].append(e.target)
        reached: set[str] = set()
        frontier = [n.key for n in test_nodes]
        while frontier:
            cur = frontier.pop()
            for t in adj.get(cur, []):
                if t not in reached:
                    reached.add(t)
                    frontier.append(t)
        route_files = {r["file"] for r in routes}
        subs = defaultdict(list)
        for n in modules:
            subs["router" if n.path in route_files else "other"].append(n)
        for role, label, sev in (("router", "Route modules", "medium"), ("other", "Other modules", "low")):
            miss = [n for n in subs[role] if n.key not in reached and (n.end or 0) > 20]
            if miss:
                b.add(f"TEST-UNREACHED-{role.upper()}", "testing", sev, "medium", "coverage_gap", f"{label} with no static link from any test ({len(miss)})",
                      f"{len(miss)} of {len(subs[role])} {label.lower()} are neither imported by a test file nor reachable through imports from one. This is import reachability, not measured coverage - tests that call the app over HTTP may still exercise them.",
                      "Add or extend tests for these modules, prioritising routes and services.", "Run the test suite with coverage (pytest --cov) to measure actual line coverage.",
                      [_ev(n.path or "", 1, None, "no test reaches this module") for n in sorted(miss, key=lambda x: x.path or "")[:12]], count=len(miss))
        b.add("TEST-RATIO", "testing", "info", "high", "metric", f"{len(test_nodes)} test file(s) for {len(modules)} module(s)", "Counts of test files versus application modules.",
              "Use as context only; ratio does not indicate quality.", "Inspect the tests themselves.", [_ev(n.path or "", 1) for n in test_nodes[:3]], count=len(test_nodes))

    # ---------------------------------------------------------------- error handling
    by_kind: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    for f in prod:
        for e in f.facts["excepts"]:
            if e["kind"] == "bare":
                by_kind["bare"].append((f.path, e))
            if e["kind"] in ("bare", "broad") and e["swallowed"] and not e["logs"] and not e["reraises"]:
                by_kind["swallow_broad"].append((f.path, e))
            elif e["kind"] == "specific" and e["swallowed"] and not e["logs"]:
                by_kind["swallow_specific"].append((f.path, e))
            elif e["kind"] == "broad" and not e["logs"] and not e["reraises"] and not e["swallowed"]:
                by_kind["broad_nolog"].append((f.path, e))
    spec = {
        "bare": ("EH-BARE-EXCEPT", "medium", "high", "Bare `except:` clauses", "A bare except also catches KeyboardInterrupt/SystemExit and hides programming errors.", "Catch specific exception types.", "Review each handler's intent."),
        "swallow_broad": ("EH-SWALLOWED-BROAD", "medium", "high", "Broad exceptions swallowed silently", "Errors are caught and discarded without logging or re-raising, which makes failures invisible.", "Log the exception (logger.exception) or let it propagate.", "Check whether the failure is genuinely safe to ignore."),
        "swallow_specific": ("EH-SWALLOWED-SPECIFIC", "low", "high", "Specific exceptions ignored without logging", "Ignoring a narrow exception is sometimes intentional (e.g. KeyError), but silent handlers can hide real problems.", "Add a comment or debug log explaining why it is ignored.", "Confirm each is intentional."),
        "broad_nolog": ("EH-BROAD-NO-LOG", "low", "high", "Broad `except Exception` without logging", "Handled but not logged, so the cause is lost.", "Log with logger.exception before handling.", "Check the handler body."),
    }
    for k, (rule, sev, conf, title, detail, rec, ver) in spec.items():
        items = by_kind.get(k, [])
        if items:
            b.add(rule, "error_handling", sev, conf, "observed", f"{title} ({len(items)})", detail, rec, ver, [_ev(p, e["line"], e["end_line"], e.get("type") or "except") for p, e in items[:12]], count=len(items))
    if routes and not any(h["kind"] == "exception_handler" for f in prod for h in f.facts["hooks"]):
        b.add("EH-NO-GLOBAL-HANDLER", "error_handling", "info", "medium", "absence", "No custom exception handlers registered", "FastAPI's default handlers apply, which return generic errors and do not log unexpected exceptions in your format.",
              "Consider @app.exception_handler for domain errors and a catch-all that logs.", "Check middleware or framework-level handling not visible to static analysis.", [],
              basis=f"Searched {len(prod)} application files for @app.exception_handler and add_exception_handler.")

    # ---------------------------------------------------------------- security / config
    grouped: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    for f in prod:
        for r in f.facts["risky"]:
            if r["kind"] == "cors_wildcard":
                continue
            grouped[r["kind"]].append((f.path, r))
    merged = {"subprocess_shell": "os_system"}
    groups: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    for kind, items in grouped.items():
        groups[merged.get(kind, kind)] += items
    for kind, items in groups.items():
        meta = RISK_RULES.get(kind)
        if meta and items:
            b.add(meta["rule"], "security", meta["severity"], meta["confidence"], "potential_risk", f"{meta['title']} ({len(items)})", meta["detail"], meta["rec"], meta["verify"],
                  [_ev(p, r["line"], None, r.get("text", "")[:80]) for p, r in sorted(items, key=lambda x: (x[0], x[1]["line"]))[:12]], count=len(items))
    cors = [(f.path, r) for f in prod for r in f.facts["risky"] if r["kind"] == "cors_wildcard"]
    if cors:
        cred = any(r.get("credentials") for _, r in cors)
        b.add("SEC-CORS-WILDCARD", "security", "high" if cred else "medium", "high", "potential_risk", "CORS allows every origin" + (" with credentials" if cred else ""),
              "allow_origins=['*']" + (" together with allow_credentials=True lets any website make credentialed requests to this API." if cred else " lets any website call this API from a browser."),
              "List the specific trusted origins.", "Check whether the API relies on cookies or other ambient credentials.", [_ev(p, r["line"], None, r["text"][:80]) for p, r in cors[:6]], count=len(cors))
    sd = [(f.path, d) for f in prod for d in f.facts["secret_defaults"]]
    if sd:
        real = [x for x in sd if not x[1]["placeholder"]]
        use = real or sd
        b.add("SEC-HARDCODED-SECRET-DEFAULT", "security", "high" if real else "medium", "medium", "potential_risk", f"Credential-like names assigned a literal value ({len(use)})",
              "Names such as SECRET_KEY/password/token are given a hard-coded string. If the value is used in production it is publicly known (the repository is public). The value is not shown here.",
              "Require the value from the environment and fail fast when it is missing.", "Check whether production overrides these defaults.", [_ev(p, d["line"], None, d["name"]) for p, d in use[:12]], count=len(use))
    red = []
    for path, lines in sorted(redactions.items()):
        if lines:
            test_like = is_test_path(path) or path.endswith((".example", ".sample", ".md")) or "fixture" in path.lower()
            red.append((path, lines, test_like))
    if red:
        main = [r for r in red if not r[2]]
        for grp, sev, conf, label in ((main, "high", "medium", "Secret-like text in source"), ([r for r in red if r[2]], "medium", "low", "Secret-like text in test/example files")):
            if grp:
                b.add("SEC-SECRET-LIKE-CONTENT", "security", sev, conf, "potential_risk", f"{label} ({sum(len(r[1]) for r in grp)} location(s))",
                      "Text matching credential patterns (tokens, private keys, password-like assignments) was found and redacted before storage. Matching is pattern-based: the value was NOT validated and may be a dummy.",
                      "Rotate any real credential, remove it from history, and load secrets from the environment.", "Inspect the lines in the original repository; do not paste the value elsewhere.",
                      [_ev(p, ln, None, "redacted") for p, lines, _ in grp for ln in lines[:2]][:12], count=sum(len(r[1]) for r in grp))
    # auth heuristics
    has_auth = any(AUTH_NAME.search(d) for r in routes for d in (graph_node_deps(nodes, r) or [])) or any(a for f in prod for a in f.facts["auth_hints"])
    mutating = [r for r in routes if r["method"] in ("POST", "PUT", "PATCH", "DELETE")]
    if routes and not has_auth:
        b.add("SEC-NO-AUTH-DETECTED", "security", "medium", "low", "absence", "No authentication mechanism detected", "No auth-style dependencies, security schemes or auth libraries were found, yet the API exposes routes.",
              "If the API is not meant to be public, add authentication.", "Check for a reverse proxy, gateway or middleware that authenticates requests.", [],
              basis=f"Searched {len(routes)} route dependency lists, security scheme constructors (OAuth2/HTTPBearer/APIKey) and {len(prod)} files.")
    elif mutating:
        unprotected = [r for r in mutating if not any(AUTH_NAME.search(d) for d in (graph_node_deps(nodes, r) or []))]
        if unprotected:
            b.add("SEC-UNAUTH-MUTATION", "security", "medium", "low", "potential_risk", f"State-changing routes without a visible auth dependency ({len(unprotected)})",
                  "These POST/PUT/PATCH/DELETE routes have no auth-looking dependency on the route, its router, or its include chain, although auth exists elsewhere in the project. Authentication may be applied by middleware, an app-level dependency, or in the handler body, which static analysis cannot see.",
                  "Confirm each is intentionally public; otherwise add an auth dependency.", "Call the route without credentials in a test environment.", [_ev(r["file"], r["decorator_line"], r["end_line"], f"{r['method']} {r['path']}") for r in unprotected[:12]], count=len(unprotected))
    # frontend sinks
    sinks = [(f.path, s) for f in web for s in f.facts.get("sinks", [])]
    if sinks:
        hard = [x for x in sinks if x[1]["kind"] in ("eval", "new Function")]
        soft = [x for x in sinks if x not in hard]
        for grp, rule, sev, conf, title in ((soft, "SEC-DOM-SINK", "medium", "low", "DOM injection sinks (innerHTML / document.write / v-html ...)"), (hard, "SEC-JS-EVAL", "medium", "medium", "JavaScript eval / new Function")):
            if grp:
                b.add(rule, "security", sev, conf, "potential_risk", f"{title} ({len(grp)})", "These APIs interpret strings as markup or code. They are only a problem when the string contains untrusted data, which static scanning cannot determine.",
                      "Prefer textContent / framework escaping; sanitize any HTML you must inject.", "Trace what data reaches each sink.", [_ev(p, s["line"], None, s["kind"]) for p, s in grp[:12]], count=len(grp))
    # config
    env_used: dict[str, tuple[str, int]] = {}
    for f in prod:
        for e in f.facts["env_vars"]:
            env_used.setdefault(e["name"], (f.path, e["line"]))
    template_names = set()
    for path, text in support.items():
        if path.rsplit("/", 1)[-1].lower() in {".env.example", ".env.sample", ".env.template", ".env.dist", "env.example"}:
            template_names |= {ln.split("=")[0].strip() for ln in text.splitlines() if "=" in ln}
    if template_names:
        missing = sorted(set(env_used) - template_names)
        if missing:
            b.add("CFG-UNDOCUMENTED-ENV", "configuration", "low", "high", "observed", f"Environment variables read but missing from the env template ({len(missing)})", "New developers will not know these must be set.",
                  "Add them to .env.example.", "Compare against deployment configuration.", [_ev(env_used[n][0], env_used[n][1], None, n) for n in missing[:12]], count=len(missing))
    elif len(env_used) >= 3:
        b.add("CFG-NO-ENV-TEMPLATE", "configuration", "low", "medium", "absence", "No .env.example found", f"The code reads {len(env_used)} environment variables but no template documents them.", "Add a .env.example with names (no values).",
              "Check README or deployment docs.", [], basis="Searched for .env.example, .env.sample, .env.template, .env.dist among stored setup files.")
    # only a module-level os.environ[...] subscript raises KeyError at import; getenv()/environ.get() return None instead
    required = [(f.path, e) for f in prod for e in f.facts["env_vars"] if e.get("how") == "os.environ[...]" and e.get("scope") is None]
    if required:
        b.add("CFG-REQUIRED-ENV-AT-IMPORT", "configuration", "info", "medium", "observed", f"Environment variables required at import time ({len(required)})", "os.environ[...] at module level raises KeyError at startup when the variable is missing.",
              "Fail with a clear message or use validated settings.", "Start the app without the variable.", [_ev(p, e["line"], None, e["name"]) for p, e in required[:12]], count=len(required))

    # ---------------------------------------------------------------- logging
    prints = [(f.path, ln) for f in prod for ln in f.facts["prints"]]
    if prints:
        b.add("LOG-PRINT", "logging", "low", "high", "observed", f"print() used in application code ({len(prints)})", "print output is unstructured, unleveled and often lost in production.", "Use the logging module.", "Check whether these are CLI scripts.",
              [_ev(p, ln) for p, ln in prints[:12]], count=len(prints))
    total_log = sum(f.facts["logger_calls"] for f in prod)
    imports_log = any(v.split(".")[0] in ("logging", "structlog", "loguru") for f in prod for v in f.facts["bindings"].values())
    if (routes or len(prod) >= 5) and total_log == 0:
        b.add("LOG-NONE", "logging", "medium", conf_cap if imports_log is False else "low", "absence", "No logging calls found in application code", "Operational problems will be hard to diagnose without logs.",
              "Add structured logging for requests, errors and external calls.", "Check for logging in middleware or libraries not analyzed.", [], basis=f"Searched {len(prod)} application files for logger/logging/log method calls ({'logging library imported' if imports_log else 'no logging library imported'}).")

    # ---------------------------------------------------------------- maintainability
    big = [(f.path, f.facts["line_count"]) for f in prod if f.facts["line_count"] > 800]
    if big:
        b.add("MAINT-LARGE-FILE", "maintainability", "medium" if any(n > 1500 for _, n in big) else "low", "high", "metric", f"Very large files ({len(big)})", "Large files are harder to review, test and change safely.",
              "Split by responsibility.", "Review file structure.", [_ev(p, 1, n, f"{n} lines") for p, n in sorted(big, key=lambda x: -x[1])[:12]], count=len(big))
    cx = [(f.path, fn) for f in prod for fn in f.facts["functions"] if fn.get("complexity", 0) > 15]
    if cx:
        worst = max(fn["complexity"] for _, fn in cx)
        b.add("MAINT-COMPLEX-FUNCTION", "maintainability", "medium" if worst > 25 else "low", "high", "metric", f"Functions with high branching complexity ({len(cx)})",
              "Cyclomatic-style count of branches and conditions (>15). High values correlate with defects and hard-to-test code.", "Extract helper functions and simplify conditionals.", "Read the functions.",
              [_ev(p, fn["line"], fn["end_line"], f"{fn['qualname']} (complexity {fn['complexity']})") for p, fn in sorted(cx, key=lambda x: -x[1]["complexity"])[:12]], count=len(cx))
    longf = [(f.path, fn) for f in prod for fn in f.facts["functions"] if fn["end_line"] - fn["line"] > 120]
    if longf:
        b.add("MAINT-LONG-FUNCTION", "maintainability", "low", "high", "metric", f"Very long functions ({len(longf)})", "Functions over 120 lines are hard to understand at a glance.", "Break into smaller functions.", "Read the functions.",
              [_ev(p, fn["line"], fn["end_line"], f"{fn['qualname']} ({fn['end_line'] - fn['line'] + 1} lines)") for p, fn in sorted(longf, key=lambda x: x[1]["line"] - x[1]["end_line"])[:12]], count=len(longf))
    many = [(f.path, fn) for f in prod for fn in f.facts["functions"] if len(fn["params"]) > 8]
    if many:
        b.add("MAINT-MANY-PARAMS", "maintainability", "low", "high", "metric", f"Functions with many parameters ({len(many)})", "More than 8 parameters suggests a missing abstraction.", "Group related parameters into a model/dataclass.", "Read the signatures.",
              [_ev(p, fn["line"], None, f"{fn['qualname']} ({len(fn['params'])} params)") for p, fn in many[:12]], count=len(many))
    adj2: dict[str, list[str]] = defaultdict(list)
    for e in graph.edges:
        s, t = nodes.get(e.source), nodes.get(e.target)
        if e.relation == "imports" and e.resolution != "unresolved" and s and t and s.type == "module" and t.type == "module" and not s.meta.get("web") and not t.meta.get("web"):
            adj2[e.source].append(e.target)
    cycles = _tarjan({k: v for k, v in adj2.items()})
    if cycles:
        ev = []
        for comp in cycles[:4]:
            cs = set(comp)
            for e in graph.edges:
                if e.relation == "imports" and e.source in cs and e.target in cs and e.evidence:
                    ev.append(_ev(e.evidence[0]["path"], e.evidence[0]["start_line"], e.evidence[0].get("end_line"), f"{nodes[e.source].name} -> {nodes[e.target].name}"))
        b.add("MAINT-IMPORT-CYCLE", "maintainability", "medium", "high", "observed", f"Circular imports between modules ({len(cycles)} group(s))", "Modules import each other directly or transitively. This can cause import-order bugs and tight coupling.",
              "Move shared code to a third module or import lazily inside functions.", "Import the modules in a fresh interpreter.", ev[:12], count=len(ev))
    todos = [(f.path, ln) for f in prod for ln in f.facts["todos"]]
    if len(todos) >= 10:
        b.add("MAINT-TODO", "maintainability", "info", "high", "metric", f"{len(todos)} TODO/FIXME/HACK comments", "Unresolved markers left in code.", "Track in an issue tracker.", "Read the comments.", [_ev(p, ln) for p, ln in todos[:12]], count=len(todos))
    failed = [f.path for f in py if f.facts is None]
    partial = [(f.path, i) for f in py if f.facts for i in f.facts.get("parse_issues") or [] if i["kind"] == "skipped"]
    if failed or partial:
        n_files = len(failed) + len({p for p, _ in partial})
        b.add("MAINT-PARSE-FAILURES", "maintainability", "low", "high", "observed",
              f"{n_files} Python file(s) could not be parsed" + (" completely" if partial else ""),
              "Static analysis (including this report) is incomplete for these files: syntax errors, unsupported newer syntax, or encoding problems."
              + (" Partially parsed files were analysed except for the listed lines." if partial else ""),
              "Fix syntax errors or run Raven on a runtime that supports the syntax.", "Run python -m py_compile on the files.",
              ([_ev(p, 1, None, "not parsed") for p in failed] + [_ev(p, i["start_line"], i["end_line"], "lines not parsed") for p, i in partial])[:12],
              count=len(failed) + len(partial))

    findings = sorted(b.findings, key=lambda x: (SEV.index(x["severity"]), CONF.index(x["confidence"]), CATEGORIES.index(x["category"]), x["rule"]))[:MAX_FINDINGS]
    sev_counts = Counter(f["severity"] for f in findings)
    cat_counts: dict[str, dict[str, int]] = {c: {} for c in CATEGORIES}
    for f in findings:
        cat_counts[f["category"]][f["severity"]] = cat_counts[f["category"]].get(f["severity"], 0) + 1
    return {"version": "1", "disclaimer": DISCLAIMER, "not_assessed": NOT_ASSESSED, "partial_analysis": partial, "findings": findings,
            "summary": {"total": len(findings), "by_severity": {s: sev_counts.get(s, 0) for s in SEV}, "by_category": cat_counts,
                        "scope": {"python_files": len(pyf), "application_files": len(prod), "test_files": len(tests), "frontend_files": len(web), "routes": len(routes)}}}


def graph_node_deps(nodes: dict[str, Any], route: dict[str, Any]) -> list[str]:
    n = nodes.get(route.get("key"))
    if n is None:
        return []
    return list(n.meta.get("dependencies", [])) + list(n.meta.get("inherited_dependencies", []))
