"""Configuration read from the environment."""
import os

DATABASE_URL = os.environ["DATABASE_URL"]
JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-me")
PAYMENT_API_KEY = os.getenv("PAYMENT_API_KEY")


class Settings:
    version = "1.4.0"
    token_ttl_minutes = 30


settings = Settings()
