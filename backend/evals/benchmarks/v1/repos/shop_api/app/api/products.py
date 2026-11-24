from fastapi import APIRouter

from app import db
from app.models import ProductOut

router = APIRouter()


@router.get("/", response_model=list[ProductOut])
def search_products(q: str = ""):
    return [ProductOut(id=r[0], name=r[1], price=float(r[2])) for r in db.find_products(q)]


@router.post("/import")
def import_catalog(path: str):
    import subprocess
    subprocess.run(f"python scripts/load_catalog.py {path}", shell=True, check=True)
    return {"queued": True}
