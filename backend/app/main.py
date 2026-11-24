from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.errors import install_error_handlers
from app.api.middleware import RequestContextMiddleware
from app.api import routes_admin, routes_analyses, routes_auth, routes_health, routes_internal, routes_pr
from app.core.config import get_settings
from app.core.logging import configure_logging, log

logger = logging.getLogger("raven.app")


def create_app() -> FastAPI:
    s = get_settings()
    configure_logging(s.log_level)
    app = FastAPI(title="Raven API", version="1.0.0", docs_url=None if s.is_production else "/api/docs",
                  redoc_url=None, openapi_url=None if s.is_production else "/api/openapi.json")
    app.add_middleware(RequestContextMiddleware)
    install_error_handlers(app)
    app.include_router(routes_health.router)
    app.include_router(routes_auth.router)
    app.include_router(routes_analyses.router)
    app.include_router(routes_pr.router)
    app.include_router(routes_admin.router)
    app.include_router(routes_internal.router)

    frontend = Path(s.frontend_dir) if s.frontend_dir else Path(__file__).resolve().parents[2] / "frontend"
    web = Path(s.web_dist_dir) if s.web_dist_dir else None
    if web is not None and (web / "index.html").is_file():  # React app at /, legacy vanilla UI kept at /legacy
        app.mount("/static", StaticFiles(directory=web / "static"), name="static")
        app.mount("/assets", StaticFiles(directory=web / "assets"), name="assets")

        @app.get("/", include_in_schema=False)
        def index_react() -> FileResponse:
            return FileResponse(web / "index.html", headers={"Cache-Control": "no-cache"})
        if frontend.is_dir():
            app.mount("/js", StaticFiles(directory=frontend / "js"), name="js")
            app.mount("/css", StaticFiles(directory=frontend / "css"), name="css")

            @app.get("/legacy", include_in_schema=False)
            def index_legacy() -> FileResponse:
                return FileResponse(frontend / "index.html", headers={"Cache-Control": "no-cache"})
    elif frontend.is_dir():
        app.mount("/assets", StaticFiles(directory=frontend / "assets"), name="assets")
        app.mount("/js", StaticFiles(directory=frontend / "js"), name="js")
        app.mount("/css", StaticFiles(directory=frontend / "css"), name="css")

        @app.get("/", include_in_schema=False)
        def index() -> FileResponse:
            return FileResponse(frontend / "index.html", headers={"Cache-Control": "no-cache"})
    if s.uses_dev_secrets():
        log(logger, "dev_secrets_in_use", logging.WARNING, note="development fallback secrets active; never use in production")
    return app


app = create_app() if not os.environ.get("RAVEN_SKIP_APP_BUILD") else None  # type: ignore[assignment]
