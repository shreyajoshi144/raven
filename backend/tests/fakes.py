"""Test doubles: fake GitHub (httpx MockTransport) and a fake Anthropic Messages API."""
from __future__ import annotations

import json
from typing import Any, Callable

import httpx

from tests.fixtures.sample_repo import SAMPLE_FILES, SHA, make_tarball


class FakeGitHub:
    def __init__(self, files: dict[str, Any] | None = None, *, sha: str = SHA, private: bool = False):
        self.files = files if files is not None else SAMPLE_FILES
        self.sha = sha
        self.private = private
        self.tarball_failures: list[int] = []  # statuses to return before succeeding
        self.repo_status = 200
        self.rate_limit_on_repo = False
        self.timeout_on_tarball = False
        self.malformed_repo = False
        self.requests: list[str] = []
        self.auth_headers: list[tuple[str, str | None]] = []
        self.redirect_host = "codeload.github.com"
        self.compare_files = [{"filename": "app/deps.py", "status": "modified", "additions": 3, "deletions": 1}, {"filename": "static/util.js", "status": "modified", "additions": 1, "deletions": 0}, {"filename": "docs/old.md", "status": "removed", "additions": 0, "deletions": 5}]
        self.parent_sha = "b" * 40
        self.known_refs = {"main", "dev", "b" * 40, "feature/x"}
        self._tar: bytes | None = None
        self.files_by_sha: dict[str, Any] = {}  # commit-specific trees (pull request base/head); falls back to `files`
        self.pulls: dict[int, dict[str, Any]] = {}

    @property
    def tarball(self) -> bytes:
        if self._tar is None:
            self._tar = make_tarball(self.files)
        return self._tar

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        self.requests.append(f"{url.host}{url.path}")
        self.auth_headers.append((url.host, request.headers.get("authorization")))
        path = url.path
        if url.host == "codeload.github.com":
            tail = path.rstrip("/").split("/")[-1]
            return httpx.Response(200, content=make_tarball(self.files_by_sha[tail]) if tail in self.files_by_sha else self.tarball, headers={"content-type": "application/x-gzip"})
        if "/pulls/" in path:
            pr = self.pulls.get(int(path.rsplit("/", 1)[1]))
            if pr is None:
                return httpx.Response(404, json={"message": "Not Found"})
            owner, name = path.split("/")[2:4]
            return httpx.Response(200, json={"number": pr["number"], "title": pr["title"], "state": pr.get("state", "open"), "merged": pr.get("merged", False),
                                             "base": {"sha": pr["base"], "repo": {"full_name": f"{owner}/{name}"}},
                                             "head": {"sha": pr["head"], "repo": {"full_name": pr.get("head_repo", f"{owner}/{name}")}}})
        if path.endswith("/rate_limit"):
            return httpx.Response(200, json={})
        if "/tarball/" in path:
            if self.timeout_on_tarball:
                raise httpx.ReadTimeout("timeout", request=request)
            if self.tarball_failures:
                return httpx.Response(self.tarball_failures.pop(0))
            return httpx.Response(302, headers={"location": f"https://{self.redirect_host}/owner/sample/legacy.tar.gz/{path.rstrip('/').split('/')[-1] if path.rstrip('/').split('/')[-1] in self.files_by_sha else self.sha}"})
        if "/compare/" in path:
            base = path.split("/compare/", 1)[1].split("...")[0]
            if base not in self.known_refs:
                return httpx.Response(404, json={"message": "Not Found"})
            return httpx.Response(200, json={"status": "ahead", "ahead_by": 2, "behind_by": 0, "merge_base_commit": {"sha": self.parent_sha}, "files": self.compare_files})
        if "/commits/" in path:
            return httpx.Response(200, json={"sha": self.sha, "parents": [{"sha": self.parent_sha}]})
        if path.count("/") == 3 and path.startswith("/repos/"):
            if self.rate_limit_on_repo:
                return httpx.Response(403, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "9999999999"}, json={"message": "API rate limit exceeded"})
            if self.repo_status != 200:
                return httpx.Response(self.repo_status, json={"message": "x"})
            if self.malformed_repo:
                return httpx.Response(200, content=b"<html>not json</html>")
            owner, name = path.split("/")[2:4]
            return httpx.Response(200, json={"full_name": f"{owner}/{name}", "html_url": f"https://github.com/{owner}/{name}", "default_branch": "main",
                                             "description": "A sample FastAPI service", "language": "Python", "size": 120, "stargazers_count": 7,
                                             "private": self.private})
        return httpx.Response(404, json={"message": "Not Found"})

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


class FakeLLM:
    """Fake Anthropic Messages API. `responder(system, user) -> str | httpx.Response` builds replies."""

    def __init__(self, responder: Callable[[str, str], Any] | None = None):
        self.responder = responder or self.default_responder
        self.calls: list[dict[str, Any]] = []
        self.status_sequence: list[int] = []

    @staticmethod
    def default_responder(system: str, user: str) -> str:
        import re
        if "onboarding notes" in system:
            paths = re.findall(r"=== FILE: (\S+) \((\d+) lines\)", user)
            return json.dumps({"explanations": [{"path": p, "summary": f"Explains {p}.", "responsibilities": ["does a thing"],
                                                  "symbols": [], "citations": [{"path": p, "start_line": 1, "end_line": 1}]} for p, _ in paths]})
        if "architecture overview" in system:
            return json.dumps({"overview": "A small FastAPI service with users and items.", "key_flows": ["Requests enter via app/main.py"],
                               "citations": [{"path": "app/main.py", "start_line": 1, "end_line": 5}]})
        # QA
        cites = re.findall(r"\[E\d+\] (\S+) lines (\d+)-(\d+)", user)
        if cites:
            p, a, b = cites[0]
            return json.dumps({"answer": f"See {p}.", "citations": [{"path": p, "start_line": int(a), "end_line": int(a)}],
                               "evidence_sufficiency": "sufficient", "limitations": []})
        return json.dumps({"answer": "No evidence.", "citations": [], "evidence_sufficiency": "insufficient", "limitations": []})

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.calls.append({"system": body["system"], "user": body["messages"][0]["content"], "headers": dict(request.headers)})
        if self.status_sequence:
            code = self.status_sequence.pop(0)
            if code >= 400:
                return httpx.Response(code, json={"error": {"type": "x"}}, headers={"retry-after": "0"} if code == 429 else {})
        out = self.responder(body["system"], body["messages"][0]["content"])
        if isinstance(out, httpx.Response):
            return out
        return httpx.Response(200, json={"content": [{"type": "text", "text": out}], "usage": {"input_tokens": 100, "output_tokens": 50}})

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)
