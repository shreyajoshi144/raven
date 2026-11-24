from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errors import ApiError, ERRORS
from app.core.logging import log, request_id_var

logger = logging.getLogger("raven.errors")


def envelope(code: str, message: str, retryable: bool, status: int, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, headers=headers,
                        content={"error": {"code": code, "message": message, "request_id": request_id_var.get(), "retryable": retryable}})


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api(_: Request, exc: ApiError) -> JSONResponse:
        return envelope(exc.code, exc.message, exc.retryable, exc.status, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        # never echo submitted values
        detail = "; ".join(f"{'.'.join(str(p) for p in e['loc'] if p != 'body')}: {e['msg']}" for e in exc.errors()[:4])
        return envelope("VALIDATION_ERROR", f"The request was not valid ({detail}).", False, 422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "NOT_FOUND", 401: "UNAUTHENTICATED", 403: "FORBIDDEN", 405: "VALIDATION_ERROR"}.get(exc.status_code, "INTERNAL_ERROR")
        meta = ERRORS[code]
        return envelope(code, "Not found." if exc.status_code == 404 else meta.message, meta.retryable, exc.status_code)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        log(logger, "unhandled_exception", logging.ERROR, error_type=type(exc).__name__)
        meta = ERRORS["INTERNAL_ERROR"]
        return envelope(meta.code, meta.message, meta.retryable, 500)
