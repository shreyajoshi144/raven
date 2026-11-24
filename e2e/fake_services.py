#!/usr/bin/env python3
"""Local stand-ins for GitHub and the Anthropic Messages API, for end-to-end tests only.

    python fake_services.py --github-port 9101 --llm-port 9102

GitHub: GET /repos/{o}/{r}, /repos/{o}/{r}/commits/{branch}, /repos/{o}/{r}/tarball/{sha} (302 -> same-host /codeload/...).
  Control: GET /__control/fail_tarball?n=2 makes the next n tarball requests return 503.
LLM:    POST /v1/messages returns schema-valid JSON grounded in the prompt (paths and line ranges are echoed from the evidence).
"""
import argparse
import json
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from tests.fixtures.sample_repo import SAMPLE_FILES, SHA, make_tarball  # noqa: E402

STATE = {"fail_tarball": 0, "tarball_requests": 0, "llm_calls": 0}
TARBALL = make_tarball(SAMPLE_FILES)


class GH(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _json(self, code, obj, headers=None):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        p = u.path
        if p == "/__control/fail_tarball":
            STATE["fail_tarball"] = int(parse_qs(u.query).get("n", ["1"])[0])
            return self._json(200, STATE)
        if p == "/__control/state":
            return self._json(200, STATE)
        m = re.match(r"^/repos/([^/]+)/([^/]+)$", p)
        if m:
            o, r = m.groups()
            if r == "missing":
                return self._json(404, {"message": "Not Found"})
            if r == "private":
                return self._json(200, {"full_name": f"{o}/{r}", "html_url": f"https://github.com/{o}/{r}", "default_branch": "main", "private": True})
            return self._json(200, {"full_name": f"{o}/{r}", "html_url": f"https://github.com/{o}/{r}", "default_branch": "main",
                                    "description": "A sample FastAPI service", "language": "Python", "size": 120, "stargazers_count": 7, "private": False})
        if re.match(r"^/repos/[^/]+/[^/]+/commits/[^/]+$", p):
            return self._json(200, {"sha": SHA})
        if re.match(r"^/repos/[^/]+/[^/]+/tarball/[0-9a-f]{40}$", p):
            STATE["tarball_requests"] += 1
            if STATE["fail_tarball"] > 0:
                STATE["fail_tarball"] -= 1
                return self._json(503, {"message": "unavailable"})
            self.send_response(302)
            self.send_header("location", f"http://{self.headers['host']}/codeload/archive.tar.gz")
            self.send_header("content-length", "0")
            self.end_headers()
            return
        if p == "/codeload/archive.tar.gz":
            self.send_response(200)
            self.send_header("content-type", "application/x-gzip")
            self.send_header("content-length", str(len(TARBALL)))
            self.end_headers()
            self.wfile.write(TARBALL)
            return
        self._json(404, {"message": "Not Found"})


class LLM(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("content-length", 0))
        body = json.loads(self.rfile.read(n))
        STATE["llm_calls"] += 1
        system, user = body["system"], body["messages"][0]["content"]
        if "onboarding notes" in system:
            files = re.findall(r"=== FILE: (\S+) \((\d+) lines\)", user)
            out = {"explanations": [{"path": p, "summary": f"{p} is part of the sample service.", "responsibilities": ["See the cited lines"], "symbols": [],
                                     "citations": [{"path": p, "start_line": 1, "end_line": 1}]} for p, _ in files]}
        elif "architecture overview" in system:
            out = {"overview": "A small FastAPI service exposing user and item routes.", "key_flows": ["Requests enter through app/main.py and are routed by include_router."],
                   "citations": [{"path": "app/main.py", "start_line": 1, "end_line": 5}]}
        else:
            ev = re.findall(r"\[E\d+\] (\S+) lines (\d+)-(\d+)", user)
            if ev:
                path, a, b = ev[0]
                out = {"answer": f"The relevant code is in {path} (see the cited lines).", "citations": [{"path": path, "start_line": int(a), "end_line": int(a)}],
                       "evidence_sufficiency": "sufficient", "limitations": ["Static analysis only; runtime behavior is not verified."]}
            else:
                out = {"answer": "The supplied evidence does not answer this.", "citations": [], "evidence_sufficiency": "insufficient", "limitations": []}
        resp = json.dumps({"content": [{"type": "text", "text": json.dumps(out)}], "usage": {"input_tokens": 120, "output_tokens": 60}}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(resp)))
        self.end_headers()
        self.wfile.write(resp)

    def do_GET(self):
        body = json.dumps(STATE).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--github-port", type=int, default=9101)
    ap.add_argument("--llm-port", type=int, default=9102)
    a = ap.parse_args()
    for port, handler in ((a.github_port, GH), (a.llm_port, LLM)):
        srv = ThreadingHTTPServer(("127.0.0.1", port), handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
    print("fake services up", flush=True)
    threading.Event().wait()
