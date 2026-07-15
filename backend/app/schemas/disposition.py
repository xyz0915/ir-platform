from pydantic import BaseModel
from typing import Optional


class DispositionCreate(BaseModel):
    action: str
    operator: str = ""
    comment: str = ""


class DispositionResponse(BaseModel):
    id: int
    event_id: str
    action: str
    operator: str
    comment: str
    created_at: str


class DispositionListResponse(BaseModel):
    items: list[DispositionResponse]
    total: int
