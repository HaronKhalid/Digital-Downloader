from pydantic import BaseModel, ConfigDict
from typing import Literal


class HistoryItemOut(BaseModel):
    id: str
    url: str
    title: str
    filename: str
    file_size: int
    source: str
    format_label: str
    completed_at: str
    file_exists: bool


class HistoryListResponse(BaseModel):
    items: list[HistoryItemOut]


class OpenHistoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["file", "folder"]
