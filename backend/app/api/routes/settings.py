from fastapi import APIRouter, Request

from ...schemas.settings import (
    CookieStatusResponse,
    SettingsResponse,
    UpdateCookiesRequest,
    UpdateSettingsRequest,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _settings(request: Request):
    return request.app.state.settings_service


@router.get("", response_model=SettingsResponse)
def get_settings(request: Request) -> SettingsResponse:
    return SettingsResponse(**_settings(request).get_all())


@router.put("", response_model=SettingsResponse)
def update_settings(body: UpdateSettingsRequest, request: Request) -> SettingsResponse:
    service = _settings(request)
    if body.output_directory is not None:
        service.update_output_directory(body.output_directory)
    if body.universal_mode is not None:
        service.set_universal_mode(body.universal_mode)
    elif body.allowed_source_domains is not None:
        service.update_allowed_domains(body.allowed_source_domains)
    return SettingsResponse(**service.get_all())


@router.get("/cookies", response_model=CookieStatusResponse)
def get_cookies_status(request: Request) -> CookieStatusResponse:
    return CookieStatusResponse(**_settings(request).get_cookies_status())


@router.post("/cookies", response_model=CookieStatusResponse)
def save_cookies(body: UpdateCookiesRequest, request: Request) -> CookieStatusResponse:
    return CookieStatusResponse(**_settings(request).save_cookies(body.cookies_content))


@router.delete("/cookies", response_model=CookieStatusResponse)
def delete_cookies(request: Request) -> CookieStatusResponse:
    return CookieStatusResponse(**_settings(request).delete_cookies())
