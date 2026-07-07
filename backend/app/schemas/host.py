"""Host Pydantic 模型."""

from typing import Optional

from pydantic import BaseModel, Field


class HostCreate(BaseModel):
    """创建主机请求模型."""
    hostname: str = Field(..., min_length=1, max_length=255, description="主机名")
    ip_address: Optional[str] = Field(None, description="IP 地址")
    os_type: Optional[str] = Field(None, pattern="^(windows|linux)$", description="操作系统类型")
    os_version: Optional[str] = Field(None, description="操作系统版本")


class HostResponse(BaseModel):
    """主机响应模型."""
    id: int
    case_id: int
    hostname: str
    ip_address: Optional[str] = None
    os_type: Optional[str] = None
    os_version: Optional[str] = None
    status: str
    agent_version: Optional[str] = None
    collection_time: Optional[str] = None
    raw_json_path: Optional[str] = None
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class ImportRecordResponse(BaseModel):
    """导入记录响应模型."""
    id: int
    host_id: int
    file_name: Optional[str] = None
    file_path: Optional[str] = None
    status: Optional[str] = None
    error_message: Optional[str] = None
    data_summary: Optional[str] = None
    imported_at: str

    class Config:
        from_attributes = True
