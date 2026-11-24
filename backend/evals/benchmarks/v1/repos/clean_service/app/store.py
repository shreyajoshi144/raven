"""SQLite-backed item store."""
import hashlib
import logging
import sqlite3

from app.settings import get_db_path

log = logging.getLogger(__name__)


def _conn() -> sqlite3.Connection:
    return sqlite3.connect(get_db_path())


def get_item(item_id: int):
    row = _conn().execute("SELECT id, name FROM items WHERE id = ?", (item_id,)).fetchone()
    return {"id": row[0], "name": row[1]} if row else None


def add_item(name: str) -> int:
    checksum = hashlib.sha256(name.encode()).hexdigest()
    try:
        cur = _conn().execute("INSERT INTO items (name, checksum) VALUES (?, ?)", (name, checksum))
    except sqlite3.IntegrityError:
        log.warning("duplicate item %s", name)
        raise
    return cur.lastrowid
