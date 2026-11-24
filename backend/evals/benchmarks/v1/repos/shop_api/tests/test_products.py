from app.api import products


def test_search_products_returns_list(monkeypatch):
    monkeypatch.setattr(products.db, "find_products", lambda q: [(1, "Pen", 2.5)])
    out = products.search_products("pen")
    assert out[0].name == "Pen"
