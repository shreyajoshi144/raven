import pytest

from app.analysis.urls import parse_github_url
from app.core.errors import ApiError


@pytest.mark.parametrize("url,expected", [
    ("https://github.com/tiangolo/fastapi", "tiangolo/fastapi"),
    ("https://github.com/tiangolo/fastapi/", "tiangolo/fastapi"),
    ("https://github.com/tiangolo/fastapi.git", "tiangolo/fastapi"),
    ("  https://github.com/a-b/c.d_e  ", "a-b/c.d_e"),
    ("HTTPS://GITHUB.COM/Owner/Repo", "Owner/Repo"),
])
def test_valid_urls(url, expected):
    assert parse_github_url(url).full_name == expected


@pytest.mark.parametrize("url", [
    "", "http://github.com/a/b", "ftp://github.com/a/b", "github.com/a/b", "https://www.github.com/a/b",
    "https://github.com.evil.com/a/b", "https://evil.com/github.com/a/b", "https://github.com@evil.com/a/b",
    "https://user:pw@github.com/a/b", "https://github.com:8443/a/b", "https://github.com:443/a/b",
    "https://github.com/a", "https://github.com/a/b/tree/main", "https://github.com/a/b?x=1", "https://github.com/a/b#frag",
    "https://github.com/a/%2e%2e", "https://github.com/a/..", "https://github.com/a/b%2Fc", "https://github.com/-a/b",
    "https://github.com/a--b/c", "https://github.com/a/b c", "https://github.com/a\\b", "https://gіthub.com/a/b",
    "https://github.com//b", "https://github.com/a/.git", "https://github.com/a/b.git.git", "https://github.com/a/b\n", "x" * 400,
    "https://github.com/a/b/../c", "javascript:alert(1)", "https://raw.githubusercontent.com/a/b",
])
def test_invalid_urls(url):
    if url == "https://github.com/a/b\n":
        # trailing whitespace is stripped; this one is actually valid
        assert parse_github_url(url).full_name == "a/b"
        return
    with pytest.raises(ApiError) as e:
        parse_github_url(url)
    assert e.value.code == "INVALID_REPOSITORY_URL"


def test_non_string():
    with pytest.raises(ApiError):
        parse_github_url(None)  # type: ignore[arg-type]
