import os


def get_db_path() -> str:
    return os.getenv("APP_DB_PATH", "inventory.db")


def get_api_token() -> str:
    token = os.getenv("API_TOKEN")
    if not token:
        raise RuntimeError("API_TOKEN is not set")
    return token
