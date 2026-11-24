from app import store


def test_get_item_is_callable(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "x.db"))
    assert callable(store.get_item)
