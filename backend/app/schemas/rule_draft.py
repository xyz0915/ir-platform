"""规则草稿相关 Pydantic 模型（P0-B）.

用于「AI 检测工程」中的规则自生成、影子运行、自动调优与人审启用链路。
前端/接口请求与响应校验均复用此处的模型。
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# 与后端枚举保持一致（避免循环依赖，这里独立声明）
SEVERITY_ENUM: List[str] = ["critical", "high", "medium", "low"]
RULE_TYPE_ENUM: List[str] = [
    "regex",
    "list",
    "threshold",
    "behavior",
    "composite",
    "exists",
    "attack_chain",
]
DRAFT_STATUS_ENUM: List[str] = [
    "draft",
    "shadow",
    "pending_review",
    "enabled",
    "rejected",
]


class RuleDraftGenerateRequest(BaseModel):
    """生成规则草稿请求."""

    sample_log_ids: Optional[List[int]] = Field(default=None, description="样本日志 ID 列表（可选）")
    category: Optional[str] = Field(default=None, description="倾向的类别")
    count: int = Field(default=1, ge=1, le=5, description="生成草稿数量")


class RuleDraftTuneRequest(BaseModel):
    """自动调优请求."""

    false_positive_examples: Optional[List[Dict[str, Any]]] = Field(
        default=None, description="误报样本（如命中了某进程/事件类型）"
    )
    feedback: Optional[str] = Field(default=None, description="分析师反馈文本")


class RuleDraftRejectRequest(BaseModel):
    """驳回请求."""

    reason: Optional[str] = Field(default=None, description="驳回原因")
