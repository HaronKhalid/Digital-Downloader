"""Routes used by the browser extension and by the Settings screen that pairs it."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi import APIRouter, Request

from ... import __version__
from ...core.config import REPO_ROOT
from ...core.errors import AppError, ErrorCode
from ...schemas.job import BatchItem, BatchRequest, BatchResponse

router = APIRouter(prefix="/api/extension", tags=["extension"])


def _key(request: Request):
    return request.app.state.extension_key


# --- key-protected (called by the extension) -------------------------------------------------


@router.get("/ping")
def ping() -> dict:
    return {"ok": True, "name": "Digital Downloader", "version": __version__}


@router.post("/send", response_model=BatchResponse)
def send(body: BatchRequest, request: Request) -> BatchResponse:
    """Queue links from the browser. Same behaviour as pasting them into the app."""
    results = request.app.state.job_service.create_batch(body.urls, body.mode)
    items = [BatchItem(**r) for r in results]
    queued = sum(1 for i in items if i.ok)
    return BatchResponse(items=items, queued=queued, failed=len(items) - queued)


# --- session-protected (called by our own Settings screen) -----------------------------------


@router.get("/pairing")
def pairing(request: Request) -> dict:
    port = request.app.state.settings.port
    key = _key(request).get()
    return {"code": f"dd1.{port}.{key}", "port": port}


@router.post("/pairing/rotate")
def rotate(request: Request) -> dict:
    key = _key(request).rotate()
    port = request.app.state.settings.port
    return {"code": f"dd1.{port}.{key}", "port": port}


def extension_directory() -> Path | None:
    """Where the unpacked extension lives (next to the app when installed, in the repo when developing)."""
    env = os.environ.get("EXTENSION_DIRECTORY")
    candidates = [Path(env)] if env else []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).parent / "extension")  # installed copy, easy for the user to find
    candidates.append(REPO_ROOT / "extension")
    for c in candidates:
        if (c / "manifest.json").is_file():
            return c
    return None


@router.post("/open-folder")
def open_folder(request: Request) -> dict:
    folder = extension_directory()
    if folder is None:
        raise AppError(ErrorCode.NOT_FOUND, "The extension folder was not found next to the app.")
    request.app.state.opener(folder / "manifest.json", select=True)
    return {"opened": True, "path": str(folder)}
