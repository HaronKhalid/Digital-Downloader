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

logger = logging.getLogger("app.errors")


class ErrorCode(str, Enum):
    INVALID_URL = "INVALID_URL"
    INVALID_REQUEST = "INVALID_REQUEST"
    NOT_FOUND = "NOT_FOUND"
    UNSUPPORTED_SOURCE = "UNSUPPORTED_SOURCE"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    MEDIA_NOT_AVAILABLE = "MEDIA_NOT_AVAILABLE"
    FORMAT_NOT_AVAILABLE = "FORMAT_NOT_AVAILABLE"
    DOWNLOAD_FAILED = "DOWNLOAD_FAILED"
    PROCESSING_FAILED = "PROCESSING_FAILED"
    FFMPEG_NOT_FOUND = "FFMPEG_NOT_FOUND"
    DISK_SPACE_LOW = "DISK_SPACE_LOW"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    JOB_CANCELLED = "JOB_CANCELLED"
    TIMEOUT = "TIMEOUT"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


class OperationCancelled(Exception):
    """The user cancelled the operation. Not an error: callers clean up and report CANCELLED."""


class AppError(Exception):
    """Expected, user-presentable failure. ``reason`` is for logs only."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        status_code: int = 400,
        reason: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.reason = reason


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
