from pydantic import BaseModel, ConfigDict, Field


class ValidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=1, max_length=4096)


class ValidateResponse(BaseModel):
    valid: bool
    normalized_url: str
    host: str
