"""Case Pydantic 模型."""

from typing import Optional

from pydantic import BaseModel, Field


class CaseCreate(BaseModel):
    """创建案件请求模型."""
    name: str = Field(..., min_length=1, max_length=255, description="案件名称")
    case_number: Optional[str] = Field(None, max_length=100, description="案件编号")
    description: Optional[str] = Field(None, description="案件描述")


class CaseUpdate(BaseModel):
    """更新案件请求模型."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    status: Optional[str] = Field(None, pattern="^(open|closed)$")


class CaseResponse(BaseModel):
    """案件响应模型."""
    id: int
    name: str
    case_number: Optional[str] = None
    description: Optional[str] = None
    status: str
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True
