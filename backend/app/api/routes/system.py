import platform

from fastapi import APIRouter, Request

from ... import __version__
from ...core.errors import AppError, ErrorCode
from ...services.ffmpeg_service import detect_ffmpeg
from ...services.sources.ytdlp import detect_ytdlp

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/dependencies")
def dependencies() -> dict:
    ffmpeg = detect_ffmpeg()
    extractor_ok, extractor_version, extractor_message = detect_ytdlp()
    return {
        "backend": {"ok": True, "version": __version__},
        "python": {"ok": True, "version": platform.python_version()},
        "ffmpeg": {"ok": ffmpeg.available, "version": ffmpeg.version, "message": ffmpeg.message},
        "extractor": {"ok": extractor_ok, "version": extractor_version, "message": extractor_message},
    }


# Plain `def` handlers: they make blocking network calls, so FastAPI runs them in a worker thread.
@router.get("/extractor/update")
def extractor_update_check(request: Request) -> dict:
    """Is a newer yt-dlp available? (Network call to the official releases.)"""
    return request.app.state.ytdlp_updater.check()


@router.post("/extractor/update")
def extractor_update(request: Request) -> dict:
    """Download, verify and install the newest yt-dlp. Refused while downloads are running."""
    if request.app.state.job_service.active_count() > 0:
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "Wait for current downloads to finish before updating.",
            status_code=409,
            reason="downloads_active",
        )
    return request.app.state.ytdlp_updater.update()
