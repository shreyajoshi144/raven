from app.main import app


def test_app_has_routes():
    assert app.routes
