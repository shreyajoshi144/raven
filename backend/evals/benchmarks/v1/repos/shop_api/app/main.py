"""Shop API entry point."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings

app = FastAPI(title="Shop API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"])
app.include_router(api_router, prefix="/api")


@app.get("/health")
def health():
    return {"status": "ok", "version": settings.version}
