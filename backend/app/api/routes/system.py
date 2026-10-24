import platform

from fastapi import APIRouter

from ... import __version__
from ...services.ffmpeg_service import detect_ffmpeg

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/dependencies")
def dependencies() -> dict:
    ffmpeg = detect_ffmpeg()
    return {
        "backend": {"ok": True, "version": __version__},
        "python": {"ok": True, "version": platform.python_version()},
        "ffmpeg": {"ok": ffmpeg.available, "version": ffmpeg.version, "message": ffmpeg.message},
    }
