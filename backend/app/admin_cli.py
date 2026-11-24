"""Promote or demote administrators:  python -m app.admin_cli grant|revoke user@example.com"""
import sys

from sqlalchemy import select

from app.core.db import new_session
from app.models import User


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] not in ("grant", "revoke"):
        print(__doc__); return 2
    with new_session() as db:
        u = db.execute(select(User).where(User.email == argv[1].strip().lower())).scalar_one_or_none()
        if u is None:
            print("No such user."); return 1
        u.role = "admin" if argv[0] == "grant" else "user"
        db.commit(); print(f"{u.email}: role={u.role}"); return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
