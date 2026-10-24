from pydantic import BaseModel, ConfigDict, Field


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=1, max_length=4096)


class FormatOut(BaseModel):
    id: str
    type: str
    container: str
    resolution: str | None
    has_audio: bool
    filesize: int | None
    filesize_approximate: bool
    label: str


class AnalyzeResponse(BaseModel):
    source: str
    source_label: str
    url: str
    title: str
    duration: int | None
    thumbnail: str | None  # verified data: URI or null
    formats: list[FormatOut]
