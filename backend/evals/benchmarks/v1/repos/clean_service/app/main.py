"""Inventory service."""
import logging

from fastapi import Depends, FastAPI, Header, HTTPException

from app import store
from app.settings import get_api_token

log = logging.getLogger(__name__)
app = FastAPI(title="Inventory")


def require_token(x_api_token: str = Header(...)) -> None:
    if x_api_token != get_api_token():
        raise HTTPException(status_code=401, detail="bad token")


@app.get("/items/{item_id}")
def read_item(item_id: int, _: None = Depends(require_token)):
    item = store.get_item(item_id)
    if item is None:
        log.info("item %s not found", item_id)
        raise HTTPException(status_code=404, detail="not found")
    return item


@app.post("/items")
def add_item(name: str, _: None = Depends(require_token)):
    return {"id": store.add_item(name)}
