"""GitHub REST client: fixed host allowlist, strict timeouts, manual redirect handling, error classification."""
from __future__ import annotations

import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from app.analysis.urls import RepoRef
from app.core.config import Settings, get_settings
from app.core.errors import JobError

CODELOAD_HOST = "codeload.github.com"
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_BRANCH_RE = re.compile(r"^[A-Za-z0-9._/\-]{1,255}$")
_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-/]{0,199}$")
MAX_JSON_BYTES = 2 * 1024 * 1024


@dataclass
class RepoMeta:
    owner: str
    name: str
    full_name: str
    html_url: str
    default_branch: str
    description: str | None
    language: str | None
    size_kb: int | None
    stars: int | None
    private: bool


class GitHubClient:
    def __init__(self, settings: Settings | None = None, transport: httpx.BaseTransport | None = None):
        self.s = settings or get_settings()
        self.api_host = urlsplit(self.s.github_api_base_url).hostname or "api.github.com"
        self.allowed_hosts = {self.api_host, CODELOAD_HOST}
        timeout = httpx.Timeout(connect=self.s.github_connect_timeout, read=self.s.github_read_timeout,
                                write=self.s.github_connect_timeout, pool=self.s.github_connect_timeout)
        self._client = httpx.Client(timeout=timeout, follow_redirects=False, transport=transport,
                                    limits=httpx.Limits(max_connections=10, max_keepalive_connections=5))

    def close(self) -> None:
        self._client.close()

    # ------------------------------------------------------------------ plumbing
    def _headers(self, url: str) -> dict[str, str]:
        h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "raven-analyzer/1.0"}
        if self.s.github_token and urlsplit(url).hostname == self.api_host:
            h["Authorization"] = f"Bearer {self.s.github_token}"  # never forwarded to other hosts
        return h

    def _check_url(self, url: str) -> None:
        parts = urlsplit(url)
        if parts.hostname not in self.allowed_hosts:
            raise JobError("GITHUB_BAD_RESPONSE", "redirect to a host outside the allowlist")
        if parts.scheme != "https" and not (self.s.allow_custom_upstreams and not self.s.is_production):
            raise JobError("GITHUB_BAD_RESPONSE", "non-https redirect")

    @staticmethod
    def _classify(resp: httpx.Response) -> JobError | None:
        code = resp.status_code
        if code < 400:
            return None
        remaining = resp.headers.get("x-ratelimit-remaining")
        retry_after = resp.headers.get("retry-after")
        body = ""
        try:
            body = resp.read().decode("utf-8", "replace")[:300].lower()
        except Exception:  # noqa: BLE001
            pass
        wait: float | None = None
        if retry_after and retry_after.isdigit():
            wait = float(retry_after)
        elif resp.headers.get("x-ratelimit-reset", "").isdigit():
            import time as _t
            wait = max(0.0, float(resp.headers["x-ratelimit-reset"]) - _t.time())
        if code == 429 or (code == 403 and (remaining == "0" or "rate limit" in body)):
            return JobError("GITHUB_RATE_LIMITED", f"status {code}", retry_after=wait)
        if code == 404:
            return JobError("REPO_NOT_FOUND", "404")
        if code == 451:
            return JobError("REPO_UNAVAILABLE", "451")
        if code in (401, 403):
            return JobError("REPO_FORBIDDEN", str(code))
        if code >= 500:
            return JobError("GITHUB_UNAVAILABLE", f"status {code}")
        return JobError("GITHUB_BAD_RESPONSE", f"status {code}")

    @contextmanager
    def _open(self, url: str) -> Iterator[httpx.Response]:
        """GET with manual, allowlist-checked redirects (max 3). Yields a streaming response."""
        current = url
        for _hop in range(4):
            self._check_url(current)
            try:
                req = self._client.build_request("GET", current, headers=self._headers(current))
                resp = self._client.send(req, stream=True)
            except httpx.TimeoutException:
                raise JobError("GITHUB_TIMEOUT", "timeout") from None
            except httpx.TransportError as exc:
                raise JobError("GITHUB_UNAVAILABLE", type(exc).__name__) from None
            if resp.status_code in (301, 302, 303, 307, 308):
                loc = resp.headers.get("location", "")
                resp.close()
                if not loc:
                    raise JobError("GITHUB_BAD_RESPONSE", "redirect without location")
                current = str(httpx.URL(current).join(loc))
                continue
            try:
                err = self._classify(resp)
                if err:
                    raise err
                yield resp
            finally:
                resp.close()
            return
        raise JobError("GITHUB_BAD_RESPONSE", "too many redirects")

    def _get_json(self, path: str) -> dict:
        url = f"{self.s.github_api_base_url}{path}"
        with self._open(url) as resp:
            try:
                raw = b""
                for chunk in resp.iter_bytes():
                    raw += chunk
                    if len(raw) > MAX_JSON_BYTES:
                        raise JobError("GITHUB_BAD_RESPONSE", "response too large")
                data = json.loads(raw)
            except (ValueError, httpx.TransportError) as exc:
                if isinstance(exc, httpx.TimeoutException):
                    raise JobError("GITHUB_TIMEOUT", "timeout") from None
                raise JobError("GITHUB_BAD_RESPONSE", "invalid JSON") from None
        if not isinstance(data, dict):
            raise JobError("GITHUB_BAD_RESPONSE", "unexpected payload shape")
        return data

    # ------------------------------------------------------------------ endpoints
    def get_repo(self, ref: RepoRef) -> RepoMeta:
        data = self._get_json(f"/repos/{ref.owner}/{ref.name}")
        try:
            full = str(data["full_name"])
            owner, _, name = full.partition("/")
            meta = RepoMeta(
                owner=owner, name=name, full_name=full, html_url=str(data["html_url"]),
                default_branch=str(data["default_branch"]), description=(data.get("description") or None),
                language=data.get("language"), size_kb=data.get("size") if isinstance(data.get("size"), int) else None,
                stars=data.get("stargazers_count") if isinstance(data.get("stargazers_count"), int) else None,
                private=bool(data.get("private", False)),
            )
        except (KeyError, TypeError):
            raise JobError("GITHUB_BAD_RESPONSE", "missing repository fields") from None
        if not meta.owner or not meta.name or not _BRANCH_RE.match(meta.default_branch):
            raise JobError("GITHUB_BAD_RESPONSE", "invalid repository identity")
        if meta.private:
            raise JobError("REPO_NOT_PUBLIC", "private")
        return meta

    def get_head_sha(self, owner: str, name: str, branch: str) -> str:
        data = self._get_json(f"/repos/{owner}/{name}/commits/{branch}")
        sha = data.get("sha")
        if not isinstance(sha, str) or not _SHA_RE.match(sha):
            raise JobError("GITHUB_BAD_RESPONSE", "invalid commit sha")
        return sha

    def get_pull(self, owner: str, name: str, number: int) -> dict:
        """Pull request identity only (commits, state, title); what changed is derived from the analysed commits, not trusted from this payload."""
        data = self._get_json(f"/repos/{owner}/{name}/pulls/{int(number)}")
        try:
            base, head = data["base"], data["head"]
            out = {"number": int(data["number"]), "title": str(data.get("title") or "")[:300], "base_sha": str(base["sha"]), "head_sha": str(head["sha"]),
                   "base_repo": str(base["repo"]["full_name"]), "head_repo": str((head.get("repo") or {}).get("full_name") or ""),
                   "state": "merged" if data.get("merged") else str(data.get("state", "open"))[:10]}
        except (KeyError, TypeError, ValueError):
            raise JobError("GITHUB_BAD_RESPONSE", "missing pull request fields") from None
        if not _SHA_RE.match(out["base_sha"]) or not _SHA_RE.match(out["head_sha"]):
            raise JobError("GITHUB_BAD_RESPONSE", "invalid pull request commits")
        return out

    @staticmethod
    def valid_ref(ref: str) -> bool:
        """Commit SHA or branch/tag name. Rejects anything that could alter the request path or the base...head syntax."""
        return bool(_REF_RE.match(ref)) and ".." not in ref and "//" not in ref and not ref.endswith(("/", ".lock", ".")) and "@{" not in ref

    def get_parent_sha(self, owner: str, name: str, sha: str) -> str | None:
        data = self._get_json(f"/repos/{owner}/{name}/commits/{sha}")
        parents = data.get("parents")
        if not isinstance(parents, list):
            raise JobError("GITHUB_BAD_RESPONSE", "missing parents")
        first = parents[0].get("sha") if parents and isinstance(parents[0], dict) else None
        return first if isinstance(first, str) and _SHA_RE.match(first) else None

    def compare(self, owner: str, name: str, base: str, head: str) -> dict:
        if not self.valid_ref(base) or not _SHA_RE.match(head):
            raise JobError("INVALID_REF", "bad ref")
        try:
            data = self._get_json(f"/repos/{owner}/{name}/compare/{base}...{head}")
        except JobError as exc:
            if exc.code == "REPO_NOT_FOUND":
                raise JobError("REF_NOT_FOUND", "compare 404") from None
            raise
        files = data.get("files")
        if not isinstance(files, list):
            raise JobError("GITHUB_BAD_RESPONSE", "missing files")
        out = []
        for f in files[:300]:
            if isinstance(f, dict) and isinstance(f.get("filename"), str) and len(f["filename"]) <= 1000:
                out.append({"path": f["filename"], "status": str(f.get("status", "modified"))[:20], "additions": int(f.get("additions") or 0), "deletions": int(f.get("deletions") or 0),
                            "previous_path": f.get("previous_filename") if isinstance(f.get("previous_filename"), str) else None})
        base_commit = data.get("merge_base_commit") or data.get("base_commit") or {}
        return {"files": out, "truncated": len(files) >= 300, "ahead_by": int(data.get("ahead_by") or 0), "behind_by": int(data.get("behind_by") or 0), "status": str(data.get("status", ""))[:20],
                "base_sha": base_commit.get("sha") if isinstance(base_commit, dict) and isinstance(base_commit.get("sha"), str) and _SHA_RE.match(base_commit["sha"]) else None}

    @contextmanager
    def open_archive(self, owner: str, name: str, sha: str) -> Iterator[Iterator[bytes]]:
        if not _SHA_RE.match(sha):
            raise JobError("GITHUB_BAD_RESPONSE", "invalid commit sha")
        url = f"{self.s.github_api_base_url}/repos/{owner}/{name}/tarball/{sha}"
        with self._open(url) as resp:
            def gen() -> Iterator[bytes]:
                try:
                    yield from resp.iter_bytes(64 * 1024)
                except httpx.TimeoutException:
                    raise JobError("GITHUB_TIMEOUT", "timeout while streaming archive") from None
                except httpx.TransportError as exc:
                    raise JobError("GITHUB_UNAVAILABLE", type(exc).__name__) from None
            yield gen()
