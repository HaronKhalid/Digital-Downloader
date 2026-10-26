"""Platform-independent error codes and exceptions for Digital Downloader Core."""

from __future__ import annotations

from enum import Enum


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
    """The user or system cancelled the operation."""


class AppError(Exception):
    """Expected, user-presentable failure. ``reason`` is for internal diagnostics."""

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
