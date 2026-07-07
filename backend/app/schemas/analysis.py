"""分析结果 Pydantic 模型."""

from typing import Any, Optional

from pydantic import BaseModel


class AnalysisResultResponse(BaseModel):
    """分析结果响应模型."""
    id: int
    host_id: int
    risk_level: str
    risk_score: int
    total_findings: int
    summary: Optional[str] = None
    details: Optional[Any] = None
    analyzed_at: str

    class Config:
        from_attributes = True


class HostProfileResponse(BaseModel):
    """主机画像响应模型."""
    id: int
    host_id: int
    cpu_info: Optional[str] = None
    memory_info: Optional[str] = None
    disk_info: Optional[str] = None
    network_info: Optional[str] = None
    installed_software: Optional[str] = None
    user_accounts: Optional[str] = None
    security_products: Optional[str] = None
    system_summary: Optional[str] = None
    created_at: str

    class Config:
        from_attributes = True


class TimelineEventResponse(BaseModel):
    """时间线事件响应模型."""
    id: int
    host_id: int
    timestamp: str
    event_type: Optional[str] = None
    source: Optional[str] = None
    description: Optional[str] = None
    severity: Optional[str] = None
    details: Optional[Any] = None

    class Config:
        from_attributes = True


class IocHitResponse(BaseModel):
    """IOC 命中响应模型."""
    id: int
    host_id: int
    ioc_type: Optional[str] = None
    ioc_value: Optional[str] = None
    matched_in: Optional[str] = None
    context: Optional[str] = None
    severity: Optional[str] = None

    class Config:
        from_attributes = True


class PersistenceItemResponse(BaseModel):
    """持久化痕迹响应模型."""
    id: int
    host_id: int
    type: Optional[str] = None
    name: Optional[str] = None
    command: Optional[str] = None
    location: Optional[str] = None
    user: Optional[str] = None
    is_suspicious: int = 0
    reason: Optional[str] = None
    details: Optional[Any] = None

    class Config:
        from_attributes = True


class SuspiciousConnectionResponse(BaseModel):
    """可疑外连响应模型."""
    id: int
    host_id: int
    protocol: Optional[str] = None
    local_address: Optional[str] = None
    local_port: Optional[int] = None
    remote_address: Optional[str] = None
    remote_port: Optional[int] = None
    state: Optional[str] = None
    process_name: Optional[str] = None
    pid: Optional[int] = None
    reason: Optional[str] = None
    rule_name: Optional[str] = None
    severity: Optional[str] = None

    class Config:
        from_attributes = True


class AbnormalProcessResponse(BaseModel):
    """异常进程响应模型."""
    id: int
    host_id: int
    pid: Optional[int] = None
    process_name: Optional[str] = None
    process_path: Optional[str] = None
    command_line: Optional[str] = None
    parent_pid: Optional[int] = None
    parent_name: Optional[str] = None
    reason: Optional[str] = None
    rule_name: Optional[str] = None
    severity: Optional[str] = None
    details: Optional[Any] = None

    class Config:
        from_attributes = True


class RuleResponse(BaseModel):
    """规则响应模型."""
    id: int
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    rule_type: Optional[str] = None
    condition: Optional[Any] = None
    severity: str = "medium"
    enabled: bool = True
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class RuleCreate(BaseModel):
    """创建规则请求模型."""
    name: str
    category: str
    rule_type: str
    condition: dict
    severity: str = "medium"
    description: Optional[str] = None


class RuleUpdate(BaseModel):
    """更新规则请求模型."""
    enabled: Optional[bool] = None
    condition: Optional[dict] = None
    severity: Optional[str] = None
