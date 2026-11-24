import pytest

from app.core.config import Settings

PROD = dict(app_env="production", database_url="postgresql://u:p@db/x", app_secret_key="a" * 40, internal_service_secret="b" * 40,
            n8n_webhook_secret="c" * 40, n8n_encryption_key="d" * 40, n8n_base_url="http://n8n:5678")


def make(**kw):
    return Settings(_env_file=None, **{**PROD, **kw})


def test_valid_production():
    s = make()
    assert s.cookie_secure is True and not s.uses_dev_secrets()


@pytest.mark.parametrize("override,needle", [
    ({"app_secret_key": ""}, "APP_SECRET_KEY is required"),
    ({"app_secret_key": "short"}, "at least 32"),
    ({"internal_service_secret": "dev-insecure-" + "x" * 30}, "placeholder"),
    ({"n8n_webhook_secret": "change-me-" + "x" * 30}, "placeholder"),
    ({"internal_service_secret": "a" * 40}, "must all differ"),
    ({"database_url": ""}, "DATABASE_URL"),
    ({"cookie_secure": False}, "COOKIE_SECURE"),
    ({"allow_custom_upstreams": True}, "ALLOW_CUSTOM_UPSTREAMS"),
    ({"github_api_base_url": "https://evil.example"}, "official GitHub API"),
    ({"n8n_base_url": ""}, "N8N_BASE_URL"),
    ({"n8n_encryption_key": ""}, "N8N_ENCRYPTION_KEY"),
])
def test_production_rejects(override, needle):
    with pytest.raises(Exception) as e:
        make(**override)
    assert needle in str(e.value)


def test_error_never_contains_secret_values():
    with pytest.raises(Exception) as e:
        make(app_secret_key="supersecretvalue-short")
    assert "supersecretvalue" not in str(e.value)


def test_dev_fallbacks_only_outside_production(monkeypatch):
    for k in ("APP_SECRET_KEY", "INTERNAL_SERVICE_SECRET", "N8N_WEBHOOK_SECRET", "N8N_BASE_URL"):
        monkeypatch.delenv(k, raising=False)
    s = Settings(_env_file=None, app_env="development", database_url="postgresql://u:p@h/d")
    assert s.uses_dev_secrets()
    assert s.database_url.startswith("postgresql+psycopg://")


def test_custom_github_only_with_flag_outside_prod():
    s = Settings(_env_file=None, app_env="test", database_url="postgresql://u:p@h/d", github_api_base_url="http://127.0.0.1:9", allow_custom_upstreams=True)
    assert s.github_api_base_url == "http://127.0.0.1:9"
    with pytest.raises(Exception):
        Settings(_env_file=None, app_env="test", database_url="postgresql://u:p@h/d", github_api_base_url="http://127.0.0.1:9")


def test_env_example_has_no_inline_comment_after_an_empty_value():
    # Docker Compose reads `KEY=   # note` as the value "# note" (it turned GITHUB_TOKEN into a bogus token -> REPO_FORBIDDEN).
    import re
    from pathlib import Path
    text = (Path(__file__).resolve().parents[2] / ".env.example").read_text()
    assert not [ln for ln in text.splitlines() if re.match(r"^[A-Z0-9_]+=\s*#", ln)]
