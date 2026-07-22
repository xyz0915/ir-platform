"""多智能体编排 + HITL 审批的请求/响应 schema（§4.3 A 节）.

遵循设计约定：后端统一返回 ``{code, data, message}`` 信封；
本模块仅定义端点入参（Pydantic），出参复用信封直接返回 dict。
"""

from typing import List, Optional

from pydantic import BaseModel, Field


class AgentRunCreate(BaseModel):
    """POST /api/agents/run 入参。"""

    event_id: Optional[str] = Field(None, description="单个安全事件 ID")
    event_ids: Optional[List[str]] = Field(None, description="批量事件 ID 列表")
    case_id: Optional[int] = Field(None, description="关联案件 ID")
    priority: Optional[str] = Field(None, description="覆盖默认 P2 优先级")
    title: Optional[str] = Field(None, description="覆盖自动生成的标题")


class AgentApprovalRequest(BaseModel):
    """POST /api/agents/runs/{run_id}/approve 入参。"""

    approval_id: int = Field(..., description="hitl_approvals 记录 ID")
    decided_by: Optional[str] = Field(None, description="决议人（实际以当前登录管理员为准）")


class AgentRejectRequest(BaseModel):
    """POST /api/agents/runs/{run_id}/reject 入参。"""

    approval_id: int = Field(..., description="hitl_approvals 记录 ID")
    reason: Optional[str] = Field(None, description="拒绝原因")


class AgentRunListItem(BaseModel):
    """agent_runs 列表项（用于文档化，实际返回走 dict 信封）。"""

    run_id: str
    event_id: Optional[str] = None
    case_id: Optional[int] = None
    title: Optional[str] = None
    stage: str = "triage"
    status: str = "pending"
    priority: str = "P2"
    confidence: float = 0.0
    user_id: Optional[int] = None
    current_agent: Optional[str] = None
    result_json: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class AgentRunResponse(BaseModel):
    """agent_runs 详情返回（比 ListItem 多一些字段）。"""

    run_id: str
    event_id: Optional[str] = None
    case_id: Optional[int] = None
    title: Optional[str] = None
    stage: str = "triage"
    status: str = "pending"
    priority: str = "P2"
    confidence: float = 0.0
    current_agent: Optional[str] = None
    user_id: Optional[int] = None
    result_json: Optional[str] = None
    ctx_json: Optional[str] = None
    steps: Optional[List[dict]] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
