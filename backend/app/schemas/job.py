from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CreateJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=1, max_length=4096)
    format_id: str = Field(min_length=1, max_length=100)
    output_format: str | None = Field(default=None, max_length=10)
    target_format: str | None = Field(default=None, max_length=10)

    @model_validator(mode="after")
    def _normalize_output(self) -> "CreateJobRequest":
        if not self.output_format and self.target_format:
            self.output_format = self.target_format
        if self.output_format == "":
            self.output_format = None
        return self


class CreateJobResponse(BaseModel):
    job_id: str
    status: str


class JobError(BaseModel):
    code: str
    message: str | None


class JobOut(BaseModel):
    job_id: str
    status: str
    title: str
    progress: float
    stage: str
    downloaded_bytes: int
    total_bytes: int | None
    speed_bps: float | None
    eta_seconds: float | None
    filename: str | None
    file_size: int | None
    error: JobError | None
    created_at: str
    started_at: str | None
    completed_at: str | None


class JobList(BaseModel):
    jobs: list[JobOut]


class OpenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["file", "folder"]
