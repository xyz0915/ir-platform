"""AI 高级功能数据模型 (Schema) — SSE 事件 + Action + 剧本 + 攻击路径."""
from __future__ import annotations
from typing import Any, Optional
from pydantic import BaseModel, Field


# ================================================================
# SSE Event Models
# ================================================================

class StreamingEvent(BaseModel):
    """SSE 流式事件基类."""
    session_id: str = ""
    intent: str = ""


class TextChunkEvent(StreamingEvent):
    """文本内容块 — 逐字渲染."""
    type: str = "text"
    content: str = ""


class CardEvent(StreamingEvent):
    """富卡片 — 内联渲染."""
    type: str = "card"
    card_type: str = ""
    data: Any = None
    action_hints: list[str] = []


class ActionConfirmEvent(StreamingEvent):
    """操作确认请求 — 高危操作需用户确认."""
    type: str = "action_confirm"
    action: str = ""
    target: str = ""
    reason: str = ""
    confirm_id: str = ""
    require_confirm: bool = True


class ActionResultEvent(StreamingEvent):
    """操作执行结果."""
    type: str = "action_result"
    action: str = ""
    status: str = ""  # completed / failed / pending
    result: dict = {}
    exec_time_ms: int = 0
    error: str = ""


class PlaybookProgressEvent(StreamingEvent):
    """剧本执行进度."""
    type: str = "playbook_progress"
    step: int = 0
    total: int = 0
    current_step_name: str = ""
    status: str = ""  # running / completed / paused / skipped


class QueryStartEvent(StreamingEvent):
    """流开始事件 — 携带元信息."""
    type: str = "query_start"
    confidence: float = 0.0


class QueryEndEvent(StreamingEvent):
    """流结束事件 — 携带汇总信息."""
    type: str = "query_end"
    usage: dict = {}
    confidence: str = ""
    source_ids: list[str] = []
    attack_path: Optional[dict] = None
    exec_time_ms: int = 0
    results_count: int = 0


# ================================================================
# Action Models
# ================================================================

class ActionIntent(BaseModel):
    """LLM 识别的操作意图."""
    action: str = ""
    target: dict = {}
    reason: str = ""
    confirm_required: bool = False
    confirm_id: str = ""


class ActionResult(BaseModel):
    """操作执行结果."""
    success: bool = True
    action: str = ""
    status: str = ""
    result: dict = {}
    error: str = ""
    rule_id: str = ""
    exec_time_ms: int = 0
    affected_hosts: list[str] = []


class ActionMapEntry(BaseModel):
    """Action 映射表条目."""
    user_intent: str = ""
    action_name: str = ""
    backend_api: str = ""
    high_risk: bool = False
    description: str = ""


# ================================================================
# Playbook Models
# ================================================================

class PlaybookStep(BaseModel):
    """剧本步骤定义."""
    id: str = ""
    name: str = ""
    type: str = ""  # query / llm / action
    params: dict = {}
    depends_on: list[str] = []


class PlaybookDef(BaseModel):
    """剧本定义."""
    id: str = ""
    name: str = ""
    description: str = ""
    steps: list[PlaybookStep] = []
    tags: list[str] = []


class StepResult(BaseModel):
    """单步执行结果."""
    step_id: str = ""
    status: str = ""  # pending / running / completed / failed / skipped
    output: Any = None
    error: str = ""
    started_at: str = ""
    completed_at: str = ""


class PlaybookStatus(BaseModel):
    """剧本执行状态."""
    playbook_id: str = ""
    session_id: str = ""
    current_step: int = 0
    total_steps: int = 0
    status: str = ""  # idle / running / paused / completed / failed
    step_results: list[StepResult] = []
    created_at: str = ""
    updated_at: str = ""


# ================================================================
# Attack Path Models
# ================================================================

class AttackPathNode(BaseModel):
    """攻击路径节点（主机/IP）."""
    id: str = ""
    label: str = ""
    hostname: str = ""
    ip: str = ""
    risk_level: str = ""
    alert_count: int = 0


class AttackPathEdge(BaseModel):
    """攻击路径边（攻击手法/时间）."""
    source_id: str = ""
    target_id: str = ""
    technique_id: str = ""
    technique_name: str = ""
    timestamp: str = ""
    evidence: str = ""


class AttackPathData(BaseModel):
    """攻击路径聚合数据."""
    nodes: list[AttackPathNode] = []
    edges: list[AttackPathEdge] = []
    summary: str = ""
    total_alerts: int = 0
    total_hosts: int = 0


# ================================================================
# Session Summary Model
# ================================================================

class SessionSummary(BaseModel):
    """会话摘要."""
    session_id: str = ""
    purpose: str = ""
    coverage: dict = {}
    key_findings: list[str] = []
    actions_taken: list[dict] = []
    status: str = ""
    generated_at: str = ""


# ================================================================
# File Upload Model
# ================================================================

class FileUpload(BaseModel):
    """多模态文件上传."""
    name: str = ""
    type: str = ""
    content_base64: str = ""
    size_bytes: int = 0


class FileParseResult(BaseModel):
    """文件解析结果."""
    success: bool = True
    file_type: str = ""
    parsed_text: str = ""
    intent: str = ""
    error: str = ""
