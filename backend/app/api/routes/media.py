import dataclasses

from fastapi import APIRouter, Request

from ...schemas.media import AnalyzeRequest, AnalyzeResponse, FormatOut
from ...utils.urls import validate_url

router = APIRouter(prefix="/api/media", tags=["media"])


# A plain `def` so FastAPI runs it in a worker thread: DNS lookups, HTTP requests and the
# extractor subprocess are all blocking.
@router.post("/analyze", response_model=AnalyzeResponse)
def analyze_media(body: AnalyzeRequest, request: Request) -> AnalyzeResponse:
    settings = request.app.state.settings
    checked = validate_url(body.url, allowed_ports=settings.allowed_ports)
    info = request.app.state.source_service.analyze(checked)
    return AnalyzeResponse(
        source=info.source_id,
        source_label=info.source_label,
        url=info.url,
        title=info.title,
        duration=info.duration,
        thumbnail=info.thumbnail,
        formats=[FormatOut(**dataclasses.asdict(f)) for f in info.formats],
    )
