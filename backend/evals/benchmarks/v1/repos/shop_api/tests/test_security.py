from app.core.security import make_token, read_token


def test_token_roundtrip():
    assert read_token(make_token(7)) == 7
