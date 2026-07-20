"""Agent 注册/心跳/断开 API + 主机在线状态."""
import logging
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
from app.schemas.agent_run import (
    AgentApprovalRequest,
    AgentRejectRequest,
    AgentRunCreate,
)

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

    默认零自主：responder 必然触发 HITL 网关，run 进入 waiting_hitl 并暂停，
    待管理员在 /approve 决议后由 reporter 收尾。
    """
    event_id = body.event_id
    event_ids = body.event_ids or ([event_id] if event_id else [])
    case_id = body.case_id
    title = f"智能体闭环-{event_id or (event_ids[0] if event_ids else 'batch')}"

    run = _orchestrator.start_run(
        event_id=event_id,
        case_id=case_id,
        title=title,
        priority="P2",
        user=current_user,
    )
    run_id = run["run_id"]
    ctx: Dict[str, Any] = {
        "event_id": event_id,
        "event_ids": event_ids,
        "case_id": case_id,
        "user": current_user,
    }
    outcome = await _orchestrator.run_pipeline(run_id, current_user, ctx)
    return {"code": 0, "data": outcome, "message": "success"}


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
    run = AgentRun.get_by_run_id(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run 不存在")
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
    run = AgentRun.get_by_run_id(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run 不存在")
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
