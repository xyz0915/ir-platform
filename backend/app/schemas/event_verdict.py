"""AI 事件研判打标 Pydantic 契约 — T-V2.

清晰定义请求 / 响应结构，便于端点校验与 QA 断言。
"""

from typing import Any, List, Optional

from pydantic import BaseModel, Field


class VerdictRequest(BaseModel):
    """POST /ai-verdict 请求体."""

    event_ids: List[Any] = Field(
        default_factory=list,
        description="待研判的事件 ID 列表（security_events.id，去重后上限 200）",
    )
    force: bool = Field(default=False, description="是否覆盖已研判事件（默认 False 跳过）")
    confidence_threshold: float = Field(
        default=0.6, ge=0.0, le=1.0, description="置信度阈值，低于此值的 suspicious 降级为 benign"
    )


class VerdictDetail(BaseModel):
    """单条事件研判状态."""

    event_id: str
    status: str  # processed | skipped | degraded | failed
    label: Optional[str] = None
    reason: Optional[str] = None
    error: Optional[str] = None


class VerdictResponse(BaseModel):
    """批量研判聚合结果."""

    processed: int = 0
    skipped: int = 0
    degraded: int = 0
    failed: int = 0
    limit: int = 200
    details: List[VerdictDetail] = Field(default_factory=list)
