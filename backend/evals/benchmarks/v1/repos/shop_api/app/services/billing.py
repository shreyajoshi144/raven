"""Payment provider client."""
import logging

import requests

from app.core.config import PAYMENT_API_KEY

log = logging.getLogger(__name__)


def charge(user_id: int, product_id: int, quantity: int) -> dict:
    resp = requests.post(
        "https://payments.example.com/v1/charges",
        json={"user": user_id, "product": product_id, "quantity": quantity},
        headers={"Authorization": f"Bearer {PAYMENT_API_KEY}"},
        timeout=10,
        verify=False,
    )
    try:
        resp.raise_for_status()
    except Exception:
        log.exception("charge failed")
        raise
    return resp.json()
