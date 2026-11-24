"""Database access with raw SQL."""
import sqlite3

from app.core.config import DATABASE_URL


def connect():
    return sqlite3.connect(DATABASE_URL)


def find_products(term: str):
    conn = connect()
    cur = conn.execute(f"SELECT id, name, price FROM products WHERE name LIKE '%{term}%'")
    return cur.fetchall()


def get_order(order_id: int):
    conn = connect()
    return conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()


def close_quietly(conn) -> None:
    try:
        conn.close()
    except Exception:
        pass
