from fastapi import APIRouter, Request

from ...schemas.settings import SettingsResponse, UpdateSettingsRequest

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _settings(request: Request):
    return request.app.state.settings_service


@router.get("", response_model=SettingsResponse)
def get_settings(request: Request) -> SettingsResponse:
    return SettingsResponse(**_settings(request).get_all())


@router.put("", response_model=SettingsResponse)
def update_settings(body: UpdateSettingsRequest, request: Request) -> SettingsResponse:
    _settings(request).update_output_directory(body.output_directory)
    return SettingsResponse(**_settings(request).get_all())
