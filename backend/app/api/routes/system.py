import platform

from fastapi import APIRouter

from ... import __version__
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
