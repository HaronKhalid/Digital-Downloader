from pydantic import BaseModel, ConfigDict, Field


class SettingsResponse(BaseModel):
    output_directory: str
    allowed_source_domains: list[str]
    universal_mode: bool = False
    has_cookies: bool = False
    max_parallel_jobs: int
    max_download_gb: int
    log_level: str


class UpdateSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    output_directory: str | None = Field(default=None, min_length=1, max_length=4096)
    allowed_source_domains: list[str] | None = Field(default=None)
    universal_mode: bool | None = Field(default=None)


class CookieStatusResponse(BaseModel):
    has_cookies: bool
    size_bytes: int = 0
    line_count: int = 0
    updated_at: float | None = None
    domains_authenticated: list[str] = Field(default_factory=list)


class UpdateCookiesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cookies_content: str = Field(..., min_length=1, max_length=5 * 1024 * 1024)
