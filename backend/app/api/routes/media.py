from fastapi import APIRouter, Request

from ...schemas.media import ValidateRequest, ValidateResponse
from ...utils.urls import validate_url

router = APIRouter(prefix="/api/media", tags=["media"])


# Declared as a plain `def` so FastAPI runs it in a worker thread: validation
# performs blocking DNS lookups. Phase 2 extends this into /analyze.
@router.post("/validate", response_model=ValidateResponse)
def validate_media_url(body: ValidateRequest, request: Request) -> ValidateResponse:
    settings = request.app.state.settings
    checked = validate_url(body.url, allowed_ports=settings.allowed_ports)
    return ValidateResponse(valid=True, normalized_url=checked.url, host=checked.host)
