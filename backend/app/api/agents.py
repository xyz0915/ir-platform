"""Agent 注册/心跳/断开 API + 主机在线状态."""
import asyncio
import logging
from dataclasses import asdict
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from app.database import get_connection
from app.models.agent_model import AgentModel
from app.services.auth_service import get_current_user
# ── 多智能体编排 + HITL 审批（P0-A）──
from app.services.agents.orchestrator import Orchestrator
from app.models.agent_run import AgentRun, AgentRunStep
from app.models.hitl_approval import HitlApproval
from app.models.agent_definition import PipelinePresetModel
from app.schemas.agent_run import (
    AgentApprovalRequest,
    AgentRejectRequest,
    AgentRunCreate,
)
from app.services.agents.default_pipeline_service import (
    DefaultPipelineService,
    DefaultPipelineError,
)
from app.schemas.default_pipeline import DefaultRuleCreate, DefaultRuleUpdate
from app.services.alert_ws import alert_ws_manager

logger = logging.getLogger(__name__)
router = APIRouter()

# 编排器单例（无状态，可安全复用）
_orchestrator = Orchestrator()


def _require_admin(user: Optional[dict]) -> None:
    """HITL 决议仅管理员可执行（§8.4）。"""
    if not user or user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可进行 HITL 审批")


# ============================================================================
# 多智能体编排 API（P0-A）
# ============================================================================

@router.post("/agents/run")
async def create_agent_run(
    body: AgentRunCreate,
    current_user: dict = Depends(get_current_user),
):
    """启动一次多智能体闭环（triage → investigation → responder[HITL] → reporter）。

    分支逻辑（config-default-pipeline）：
    - 若 ``preset_id`` 给定（P1-3 手动覆盖）→ 直接取 preset.agents 走 run_custom_pipeline（mode='custom'）；
    - 否则后端自动 ``resolve_default_pipeline``：命中 scene/global → run_custom_pipeline；
      全无默认配置 → 回退硬编码 run_pipeline（4 阶段，行为完全不变）。

    该端点立即返回，pipeline 在后台异步执行（P1-5 BackgroundTasks）。
    """
    event_id = body.event_id
    event_ids = body.event_ids or ([event_id] if event_id else [])
    case_id = body.case_id
    title = body.title or f"智能体闭环-{event_id or (event_ids[0] if event_ids else 'batch')}"

    ctx: Dict[str, Any] = {
        "run_id": "",  # 占位，start_run 后填充
        "event_id": event_id,
        "event_ids": event_ids,
        "case_id": case_id,
        "user": current_user,
    }

    agent_names: Optional[list] = None

    # ── 1) 手动覆盖：显式指定 preset_id ──
    if body.preset_id is not None:
        preset = PipelinePresetModel.get(body.preset_id)
        if not preset:
            raise HTTPException(status_code=400, detail=f"preset_id={body.preset_id} 不存在")
        agent_names = preset.get("agents") or []
        ctx["mode"] = "custom"
        ctx["agent_names"] = list(agent_names)
    else:
        # ── 2) 自动匹配：resolve 三级解析 ──
        resolved = DefaultPipelineService().resolve_default_pipeline(
            {"event_id": event_id}
        )
        if resolved.match_type in ("scene", "global"):
            agent_names = resolved.agent_names
            ctx["mode"] = "custom"
            ctx["agent_names"] = list(agent_names)
            ctx["resolved_rule_id"] = resolved.rule_id
            ctx["resolved_match_type"] = resolved.match_type

    run = _orchestrator.start_run(
        event_id=event_id,
        case_id=case_id,
        title=title,
        priority=body.priority or "P2",
        user=current_user,
        ctx_json=_safe_json(ctx),
    )
    run_id = run["run_id"]
    ctx["run_id"] = run_id

    # ── 3) 执行：有 agent_names → 自定义/默认管道；否则硬编码兜底 ──
    if agent_names:
        asyncio.create_task(
            _orchestrator.run_custom_pipeline(
                run_id, agent_names, event_id, current_user, ensure_reporter=True
            )
        )
    else:
        asyncio.create_task(_orchestrator.run_pipeline(run_id, current_user, ctx))

    return {"code": 0, "data": {"run_id": run_id, "status": "pending"}, "message": "pipeline started"}


# ============================================================================
# 可配置默认闭环流程（config-default-pipeline）：规则 CRUD + resolve 预览
# ============================================================================

def _model_dump(model: BaseModel, exclude_unset: bool = False) -> dict:
    """Pydantic v1/v2 兼容的 dict 导出."""
    if hasattr(model, "model_dump"):
        return model.model_dump(exclude_unset=exclude_unset)
    return model.dict(exclude_unset=exclude_unset)


@router.get("/agents/default-pipelines/resolve")
def resolve_default_pipeline_preview(
    event_id: Optional[str] = Query(None, description="安全事件 ID"),
    category: Optional[str] = Query(None, description="显式覆盖 category"),
    priority: Optional[str] = Query(None, description="显式覆盖 priority"),
    current_user: dict = Depends(get_current_user),
):
    """resolve 预览（运行页 banner / 管理页）。

    返回 ResolveResult：match_type(scene/global/hardcoded) + preset 信息 + rule_id + scene_condition。
    允许前端显式传 category/priority 覆盖映射（§7.4）。
    """
    result = DefaultPipelineService().resolve_default_pipeline(
        {"event_id": event_id, "category": category, "priority": priority}
    )
    return {"code": 0, "data": asdict(result), "message": "ok"}


@router.get("/agents/default-pipelines")
def list_default_rules(
    current_user: dict = Depends(get_current_user),
):
    """列出全部默认规则（管理列表）。"""
    return {
        "code": 0,
        "data": DefaultPipelineService().list_rules(),
        "message": "ok",
    }


@router.post("/agents/default-pipelines")
def create_default_rule(
    body: DefaultRuleCreate,
    current_user: dict = Depends(get_current_user),
):
    """新建默认规则（仅管理员）。"""
    _require_admin(current_user)
    try:
        rule = DefaultPipelineService().create_rule(_model_dump(body), current_user)
    except DefaultPipelineError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    return {"code": 0, "data": rule, "message": "ok"}


@router.put("/agents/default-pipelines/{rule_id}")
def update_default_rule(
    rule_id: int,
    body: DefaultRuleUpdate,
    current_user: dict = Depends(get_current_user),
):
    """编辑默认规则（仅管理员）。"""
    _require_admin(current_user)
    try:
        rule = DefaultPipelineService().update_rule(rule_id, _model_dump(body, exclude_unset=True))
    except DefaultPipelineError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    return {"code": 0, "data": rule, "message": "ok"}


@router.delete("/agents/default-pipelines/{rule_id}")
def delete_default_rule(
    rule_id: int,
    current_user: dict = Depends(get_current_user),
):
    """删除默认规则（仅管理员）。删全局默认且无其它全局时回退硬编码（fell_back_to_hardcoded）。"""
    _require_admin(current_user)
    try:
        result = DefaultPipelineService().delete_rule(rule_id)
    except DefaultPipelineError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    return {"code": 0, "data": result, "message": "ok"}


@router.post("/agents/runs/{run_id}/cancel")
def cancel_agent_run(
    run_id: str,
    current_user: dict = Depends(get_current_user),
):
    """取消正在运行的编排（仅管理员）。"""
    _require_admin(current_user)
    run = AgentRun.get_by_run_id(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.get("status") not in ("pending", "running", "waiting_hitl"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel run in status: {run.get('status')}",
        )
    AgentRun.update(run_id, status="cancelled")
    return {"code": 0, "data": {"run_id": run_id, "status": "cancelled"}}


@router.websocket("/agents/ws")
async def agent_orchestration_websocket(websocket: WebSocket):
    """Agent 编排 WebSocket — 接收前端连接并广播状态变更。"""
    await alert_ws_manager.connect(0, websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # 接受 ping/pong 维持连接
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        alert_ws_manager.disconnect(0, websocket)


@router.get("/agents/runs")
def list_agent_runs(
    status: Optional[str] = Query(None, description="按状态过滤"),
    priority: Optional[str] = Query(None, description="按优先级过滤"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    """分页列出 agent_runs（含可选状态/优先级过滤）。"""
    data = AgentRun.list_all(status=status, page=page, page_size=page_size)
    if priority:
        data["items"] = [r for r in data["items"] if r.get("priority") == priority]
        data["total"] = len(data["items"])
    return {"code": 0, "data": data, "message": "success"}


@router.get("/agents/runs/{run_id}")
def get_agent_run(
    run_id: str,
    current_user: dict = Depends(get_current_user),
):
    """获取单次运行详情（含阶段步骤 steps[]）。"""
    run = AgentRun.get_by_run_id(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run 不存在")
    steps = AgentRunStep.list_by_run(run_id)
    return {"code": 0, "data": {"run": run, "steps": steps}, "message": "success"}


@router.post("/agents/runs/{run_id}/approve")
async def approve_agent_run(
    run_id: str,
    body: AgentApprovalRequest,
    current_user: dict = Depends(get_current_user),
):
    """HITL 批准：仅管理员。决议后由 Responder 经 ActionService 执行 + 写处置记录 + 报告收尾。"""
    _require_admin(current_user)
    approval = HitlApproval.get_by_id(body.approval_id)
    if not approval or approval.get("run_id") != run_id:
        raise HTTPException(status_code=404, detail="审批记录不存在或不匹配该 run")
    if approval.get("status") != HitlApproval.STATUS_PENDING:
        raise HTTPException(status_code=409, detail="该审批已被决议")

    HitlApproval.update_status(
        body.approval_id,
        HitlApproval.STATUS_APPROVED,
        decided_by=current_user.get("id"),
        reason=None,
    )
    approval = HitlApproval.get_by_id(body.approval_id)
    outcome = await _orchestrator.resume(
        run_id, approval, decided_by=current_user.get("id"), user=current_user
    )
    return {
        "code": 0,
        "data": {
            "status": "approved",
            "executed": outcome.get("executed"),
            "run": outcome,
        },
        "message": "success",
    }


@router.post("/agents/runs/{run_id}/reject")
async def reject_agent_run(
    run_id: str,
    body: AgentRejectRequest,
    current_user: dict = Depends(get_current_user),
):
    """HITL 拒绝：仅管理员。拒绝后转人工研判，run 由 reporter 收尾（标注拒绝）。"""
    _require_admin(current_user)
    approval = HitlApproval.get_by_id(body.approval_id)
    if not approval or approval.get("run_id") != run_id:
        raise HTTPException(status_code=404, detail="审批记录不存在或不匹配该 run")
    if approval.get("status") != HitlApproval.STATUS_PENDING:
        raise HTTPException(status_code=409, detail="该审批已被决议")

    HitlApproval.update_status(
        body.approval_id,
        HitlApproval.STATUS_REJECTED,
        decided_by=current_user.get("id"),
        reason=body.reason,
    )
    approval = HitlApproval.get_by_id(body.approval_id)
    outcome = await _orchestrator.resume(
        run_id, approval, decided_by=current_user.get("id"), user=current_user
    )
    return {
        "code": 0,
        "data": {"status": "rejected", "run": outcome},
        "message": "success",
    }


@router.get("/agents/approvals")
def list_pending_approvals(
    status: str = Query("pending"),
    current_user: dict = Depends(get_current_user),
):
    """列出待审批的 HITL 记录（仅管理员）。"""
    _require_admin(current_user)
    data = HitlApproval.list_pending()
    return {"code": 0, "data": data, "message": "success"}


class AgentRegisterRequest(BaseModel):
    host_id: int
    agent_version: Optional[str] = None
    os_type: Optional[str] = None
    collectors: Optional[list] = None
    ip_address: Optional[str] = None


class HeartbeatRequest(BaseModel):
    agent_id: Optional[str] = None
    cpu: Optional[float] = None
    memory: Optional[float] = None


@router.post("/agents/register")
def register_agent(data: AgentRegisterRequest, current_user: dict = Depends(get_current_user)):
    """注册 Agent."""
    result = AgentModel.register(
        host_id=data.host_id,
        agent_version=data.agent_version,
        os_type=data.os_type,
        collectors=data.collectors,
        ip_address=data.ip_address,
    )
    if not result:
        return {"success": False, "error": "Agent 注册失败"}
    return {"success": True, "data": result}


@router.post("/hosts/{host_id}/heartbeat")
def agent_heartbeat(host_id: int, data: HeartbeatRequest = None,
                    current_user: dict = Depends(get_current_user)):
    """Agent 心跳."""
    ok = AgentModel.heartbeat(host_id)
    return {"success": ok, "status": "ok"}


@router.post("/hosts/{host_id}/disconnect")
def agent_disconnect(host_id: int, current_user: dict = Depends(get_current_user)):
    """Agent 断开."""
    ok = AgentModel.disconnect(host_id)
    return {"success": ok}


@router.get("/agents/online")
def online_hosts(timeout: int = Query(90), current_user: dict = Depends(get_current_user)):
    """获取在线主机列表."""
    hosts = AgentModel.get_online_hosts(timeout_seconds=timeout)
    return {"success": True, "data": hosts}


@router.get("/agents/online-status")
def all_hosts_status(timeout: int = Query(90), current_user: dict = Depends(get_current_user)):
    """获取所有主机的在线/离线状态."""
    hosts = AgentModel.get_all_with_status(timeout_seconds=timeout)
    return {"success": True, "data": hosts}


@router.get("/agents")
def list_agents(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    """获取 Agent 列表（关联 hosts 表返回主机名）."""
    offset = (page - 1) * page_size
    with get_connection() as conn:
        count_row = conn.execute("SELECT COUNT(*) as cnt FROM agents").fetchone()
        total = count_row["cnt"] if count_row else 0

        rows = conn.execute(
            "SELECT a.*, h.hostname, h.case_id "
            "FROM agents a LEFT JOIN hosts h ON h.id = a.host_id "
            "ORDER BY a.last_heartbeat DESC LIMIT ? OFFSET ?",
            (page_size, offset),
        ).fetchall()

    items = [dict(r) for r in rows]
    return {"code": 0, "data": {"total": total, "items": items}, "message": "success"}


@router.get("/agents/stats")
def get_agent_stats(
    current_user: dict = Depends(get_current_user),
):
    """获取 Agent 统计（总数/在线/离线）."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT "
            "  COUNT(*) as total, "
            "  SUM(CASE WHEN status='online' THEN 1 ELSE 0 END) as online, "
            "  SUM(CASE WHEN status='offline' OR status IS NULL THEN 1 ELSE 0 END) as offline "
            "FROM agents"
        ).fetchone()

    data = {
        "total": int(row["total"]) if row and row["total"] else 0,
        "online": int(row["online"]) if row and row["online"] else 0,
        "offline": int(row["offline"]) if row and row["offline"] else 0,
    }
    return {"code": 0, "data": data, "message": "success"}


def _safe_json(obj: Any) -> str:
    """安全 JSON 序列化（失败退回字符串）。"""
    import json

    try:
        return json.dumps(obj, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(obj)
