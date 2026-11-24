"""Strict GitHub repository URL canonicalization (spec section 7)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from app.core.errors import ApiError

_OWNER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
_REPO_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
_MAX_URL_LEN = 200


@dataclass(frozen=True)
class RepoRef:
    owner: str
    name: str

    @property
    def canonical_url(self) -> str:
        return f"https://github.com/{self.owner}/{self.name}"

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"


def _invalid(reason: str) -> ApiError:
    return ApiError("INVALID_REPOSITORY_URL", f"Invalid repository URL: {reason}.")


def parse_github_url(raw: str) -> RepoRef:
    """Accept only https://github.com/<owner>/<repo>[.git][/] and nothing else."""
    if not isinstance(raw, str):
        raise _invalid("expected text")
    url = raw.strip()
    if not url or len(url) > _MAX_URL_LEN:
        raise _invalid("empty or too long")
    if not url.isascii() or any(ord(c) < 33 or ord(c) == 127 for c in url):
        raise _invalid("contains whitespace, control or non-ASCII characters")
    if "%" in url or "\\" in url or "?" in url or "#" in url or "@" in url:
        raise _invalid("encoded characters, userinfo, query strings and fragments are not allowed")
    if not url.lower().startswith("https://"):
        raise _invalid("only https:// URLs are accepted")
    try:
        parts = urlsplit(url)
        host = parts.hostname
        port = parts.port
    except ValueError:
        raise _invalid("malformed URL") from None
    if parts.username is not None or parts.password is not None:
        raise _invalid("userinfo is not allowed")
    if port is not None:
        raise _invalid("custom ports are not allowed")
    if host is None or host.lower() != "github.com" or parts.netloc.lower() != "github.com":
        raise _invalid("host must be exactly github.com")
    if parts.query or parts.fragment:
        raise _invalid("query strings and fragments are not allowed")

    path = parts.path
    if path.endswith("/"):
        path = path[:-1]
    segments = path.split("/")
    # path starts with "/" so segments[0] == ""
    if len(segments) != 3 or segments[0] != "" or not segments[1] or not segments[2]:
        raise _invalid("expected exactly /owner/repository")
    owner, repo = segments[1], segments[2]
    if repo.lower().endswith(".git"):
        repo = repo[:-4]
    if not repo or repo in {".", ".."} or repo.endswith(".git"):
        raise _invalid("repository name is not valid")
    if not _OWNER_RE.match(owner) or "--" in owner:
        raise _invalid("owner name is not valid")
    if not _REPO_RE.match(repo):
        raise _invalid("repository name is not valid")
    return RepoRef(owner=owner, name=repo)


_PR_RE = re.compile(r"^(https://github\.com/[^/]+/[^/]+)/pull/([1-9][0-9]{0,8})/?$")


def parse_pr_url(raw: str) -> tuple[RepoRef, int]:
    """Accept only https://github.com/<owner>/<repo>/pull/<number>; the repository part goes through the strict repository parser."""
    m = _PR_RE.match(raw.strip()) if isinstance(raw, str) else None
    if not m:
        raise _invalid("expected https://github.com/<owner>/<repo>/pull/<number>")
    return parse_github_url(m.group(1)), int(m.group(2))
