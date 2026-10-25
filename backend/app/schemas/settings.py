from pydantic import BaseModel, ConfigDict, Field


class SettingsResponse(BaseModel):
    output_directory: str
    allowed_source_domains: list[str]
    max_parallel_jobs: int
    max_download_gb: int
    log_level: str


class UpdateSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    output_directory: str = Field(min_length=1, max_length=4096)
