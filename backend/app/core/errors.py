"""Structured application errors and the JSON error envelope.

Every error response has the shape ``{"error": {"code": ..., "message": ...}}``.
Messages are written for end users; stack traces and internal detail never
leave the backend.
"""

from __future__ import annotations

import logging
from enum import Enum

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from core.errors import AppError, ErrorCode, OperationCancelled

logger = logging.getLogger("app.errors")


def error_body(code: ErrorCode | str, message: str) -> dict:
    value = code.value if isinstance(code, ErrorCode) else code
    return {"error": {"code": value, "message": message}}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        logger.warning(
            "request rejected",
            extra={"operation": request.url.path, "status": "rejected",
                   "error_code": exc.code.value, "reason": exc.reason},
        )
        return JSONResponse(error_body(exc.code, exc.message), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        logger.info("malformed request body", extra={"operation": request.url.path, "status": "rejected"})
        return JSONResponse(
            error_body(ErrorCode.INVALID_REQUEST, "The request was not valid."), status_code=400
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 404:
            body = error_body(ErrorCode.NOT_FOUND, "That resource was not found.")
        elif exc.status_code == 405:
            body = error_body(ErrorCode.INVALID_REQUEST, "That method is not supported here.")
        else:
            body = error_body(ErrorCode.UNKNOWN_ERROR, "The request could not be completed.")
        return JSONResponse(body, status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error", extra={"operation": request.url.path, "status": "failed"})
        return JSONResponse(
            error_body(ErrorCode.UNKNOWN_ERROR, "Something went wrong. Check the application log for details."),
            status_code=500,
        )
