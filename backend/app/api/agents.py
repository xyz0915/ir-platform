"""Agent 注册/心跳/断开 API + 主机在线状态."""
import asyncio
import logging
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from app.database import get_connection
from app.models.agent_model import AgentModel
from app.services.auth_service import get_current_user
from app.services.agent_auth import assert_host_binding, get_current_agent
from app.services.audit_service import create_audit_log
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

    # P1-1: 同步校验 DAG 合法性（缺失/禁用 agent、有环 → 即时 400，不静默丢节点）
    if agent_names:
        from app.services.agents.agent_registry import AgentRegistry
        validation_errors = AgentRegistry().validate_pipeline(agent_names)
        blocking_errors = [
            m for m in validation_errors
            if "not found" in m or "disabled" in m or "Circular" in m
        ]
        if blocking_errors:
            raise HTTPException(status_code=400, detail="; ".join(blocking_errors))

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
    # P2-6: 引擎内取消配套（唤醒 waiting_hitl + 中断在途任务）
    try:
        from app.services.agents.pipeline_engine import pipeline_engine
        pipeline_engine.cancel(run_id)
    except Exception as exc:
        logger.warning("pipeline_engine.cancel 失败 run_id=%s: %s", run_id, exc)
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


class AgentBootstrapRequest(BaseModel):
    """Agent 自举注册请求体（除 hostname 外全可选）. """

    hostname: Optional[str] = None
    ip_address: Optional[str] = None
    os_type: Optional[str] = None
    agent_version: Optional[str] = None
    collectors: Optional[list] = None


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


@router.post("/agents/{host_id}/token")
def generate_agent_token(host_id: int, current_user: dict = Depends(get_current_user)):
    """生成/重置 Agent 专属 token（幂等：POST 即生成/重置，旧 token 立即失效）.

    - 明文 token 仅本次响应返回一次，响应后不可再查（前端短暂持有用于复制部署命令）；
    - host 不存在 → 404；host 存在但 agents 无记录时自动补齐一行再写入 token_hash；
    - 操作写入通用操作日志表 audit_logs（不含 token 明文）。
    """
    with get_connection() as conn:
        host = conn.execute("SELECT id FROM hosts WHERE id=?", [host_id]).fetchone()
    if not host:
        raise HTTPException(status_code=404, detail=f"host {host_id} 不存在")

    # host 存在但 agents 行缺失时自动补齐（沿用 register() 的 INSERT 逻辑）
    with get_connection() as conn:
        row = conn.execute(
            "SELECT agent_id FROM agents WHERE host_id=?", [host_id]
        ).fetchone()
        if not row:
            conn.execute(
                "INSERT OR IGNORE INTO agents (host_id, agent_id) VALUES (?, ?)",
                [host_id, f"agent-{uuid.uuid4().hex[:12]}"],
            )

    result = AgentModel.generate_token(host_id)
    if not result:
        raise HTTPException(status_code=500, detail="token 生成失败")

    try:
        create_audit_log(
            user_id=current_user.get("id"),
            username=current_user.get("username") or "",
            action_type="agent_token_generate",
            detail=f"生成/重置 Agent token host_id={host_id} agent_id={result['agent_id']}",
            target_type="agent",
            target_id=str(host_id),
        )
    except Exception as exc:
        logger.warning("写入 agent token 审计日志失败: %s", exc)

    return {
        "code": 0,
        "data": {
            "host_id": result["host_id"],
            "agent_id": result["agent_id"],
            "token": result["token"],
            "token_created_at": result.get("token_created_at"),
            "token_set": True,
        },
        "message": "success",
    }


@router.post("/agents/bootstrap")
def agent_bootstrap(data: AgentBootstrapRequest, agent: dict = Depends(get_current_agent)):
    """Agent 自举注册：凭 token 认领 host_id 并刷新主机元数据.

    - token 命中 agents 行 → 取 host_id → 刷新 agents 元数据（ip/os/version/collectors/心跳）
      与 hosts 元数据（hostname/ip/os_type）；
    - 刷新元数据让「先建主机后部署 agent」流程下平台信息保持最新。
    """
    host_id = int(agent["host_id"])
    with get_connection() as conn:
        exists = conn.execute(
            "SELECT 1 FROM agents WHERE host_id=?", [host_id]
        ).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="agent 绑定主机不存在")

        agent_fields: List[str] = []
        agent_values: List[Any] = []
        if data.ip_address is not None:
            agent_fields.append("ip_address=?")
            agent_values.append(data.ip_address)
        if data.os_type is not None:
            agent_fields.append("os_type=?")
            agent_values.append(data.os_type)
        if data.agent_version is not None:
            agent_fields.append("agent_version=?")
            agent_values.append(data.agent_version)
        if data.collectors is not None:
            agent_fields.append("collectors=?")
            agent_values.append(",".join(data.collectors))
        agent_fields.append("status='online'")
        agent_fields.append("last_heartbeat=datetime('now')")
        if agent_fields:
            conn.execute(
                f"UPDATE agents SET {', '.join(agent_fields)} WHERE host_id=?",
                agent_values + [host_id],
            )

        host_fields: List[str] = []
        host_values: List[Any] = []
        if data.hostname is not None:
            host_fields.append("hostname=?")
            host_values.append(data.hostname)
        if data.ip_address is not None:
            host_fields.append("ip_address=?")
            host_values.append(data.ip_address)
        if data.os_type is not None:
            host_fields.append("os_type=?")
            host_values.append(data.os_type)
        if host_fields:
            conn.execute(
                f"UPDATE hosts SET {', '.join(host_fields)}, updated_at=datetime('now') WHERE id=?",
                host_values + [host_id],
            )

    return {
        "code": 0,
        "data": {
            "host_id": host_id,
            "agent_id": agent["agent_id"],
            "token_valid": True,
        },
        "message": "success",
    }


@router.post("/hosts/{host_id}/heartbeat")
def agent_heartbeat(host_id: int, data: HeartbeatRequest = None,
                    agent: dict = Depends(get_current_agent)):
    """Agent 心跳（agent token 认证 + host_id 绑定校验）."""
    assert_host_binding(agent, host_id)
    ok = AgentModel.heartbeat(host_id)
    return {"success": ok, "status": "ok"}


@router.post("/hosts/{host_id}/disconnect")
def agent_disconnect(host_id: int, agent: dict = Depends(get_current_agent)):
    """Agent 断开（agent token 认证 + host_id 绑定校验）."""
    assert_host_binding(agent, host_id)
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


_ONLINE_WINDOW_SECONDS = 90  # 心跳窗口：last_heartbeat 距今 ≤90s 视为在线（惰性折算）


def _derive_online_status(last_heartbeat: Optional[str]) -> str:
    """按 90s 心跳窗口惰性折算在线状态（与 get_agent_stats 口径一致）.

    last_heartbeat 由 SQLite ``datetime('now')``（UTC）写入，比较必须统一 UTC 基准，
    否则 UTC+8 环境下刚心跳的主机会被误判为 offline（曾见 D-1）。
    """
    if not last_heartbeat:
        return "offline"
    try:
        hb = datetime.strptime(str(last_heartbeat), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        try:
            hb = datetime.fromisoformat(str(last_heartbeat))
        except ValueError:
            return "offline"
    # 统一 UTC 基准：naive 一律视为 UTC；aware 先转 UTC 再剥去 tzinfo，避免类型冲突
    if hb.tzinfo is not None:
        hb = hb.astimezone(timezone.utc).replace(tzinfo=None)
    if (datetime.now(timezone.utc).replace(tzinfo=None) - hb).total_seconds() <= _ONLINE_WINDOW_SECONDS:
        return "online"
    return "offline"


@router.get("/agents")
def list_agents(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    case_id: Optional[int] = Query(None, description="按案件过滤；不传则返回全平台"),
    current_user: dict = Depends(get_current_user),
):
    """获取 Agent 列表（hosts 为主表，关联 agents 返回 agent 状态）.

    主机 Agent 页管理的是「平台上的所有主机 + 各自的 agent 接入状态」，
    因此以 hosts 为主表 LEFT JOIN agents：未注册/未生成 token 的主机也展示，
    操作列可对其「生成 Token」（后端自动补齐 agents 行）。

    在线状态按 last_heartbeat 90s 窗口惰性折算；附带 token_set/token_created_at，
    不返回 token_hash / token 明文。

    case_id 用于「案件维度」收敛：传入时仅返回该案件下的主机 agent，
    不传则保持全平台视角（兼容既有调用）。
    """
    offset = (page - 1) * page_size
    with get_connection() as conn:
        if case_id is not None:
            count_row = conn.execute(
                "SELECT COUNT(*) as cnt FROM hosts WHERE case_id=?", (case_id,)
            ).fetchone()
            rows = conn.execute(
                "SELECT h.id AS host_id, h.hostname, h.case_id, h.ip_address, h.os_type, "
                "       a.agent_id, a.agent_version, a.last_heartbeat, a.token_hash, a.token_created_at "
                "FROM hosts h LEFT JOIN agents a ON h.id = a.host_id "
                "WHERE h.case_id = ? "
                "ORDER BY COALESCE(a.last_heartbeat, '') DESC, h.id DESC "
                "LIMIT ? OFFSET ?",
                (case_id, page_size, offset),
            ).fetchall()
        else:
            count_row = conn.execute("SELECT COUNT(*) as cnt FROM hosts").fetchone()
            rows = conn.execute(
                "SELECT h.id AS host_id, h.hostname, h.case_id, h.ip_address, h.os_type, "
                "       a.agent_id, a.agent_version, a.last_heartbeat, a.token_hash, a.token_created_at "
                "FROM hosts h LEFT JOIN agents a ON h.id = a.host_id "
                "ORDER BY COALESCE(a.last_heartbeat, '') DESC, h.id DESC "
                "LIMIT ? OFFSET ?",
                (page_size, offset),
            ).fetchall()

    total = count_row["cnt"] if count_row else 0
    items = []
    for r in rows:
        item = dict(r)
        item["status"] = _derive_online_status(item.get("last_heartbeat"))
        item["token_set"] = bool(item.get("token_hash"))
        item["token_created_at"] = item.get("token_created_at")
        item.pop("token_hash", None)  # 禁止返回 token_hash
        items.append(item)
    return {"code": 0, "data": {"total": total, "items": items}, "message": "success"}


@router.get("/agents/stats")
def get_agent_stats(
    case_id: Optional[int] = Query(None, description="按案件过滤；不传则返回全平台"),
    current_user: dict = Depends(get_current_user),
):
    """获取 Agent 统计（总数/在线/离线）.

    与列表同口径：以 hosts 表为总数基准，online/offline 按 last_heartbeat
    90s 窗口惰性折算（未注册 agent 的主机计入 offline）。

    case_id 用于「案件维度」收敛：传入时仅统计该案件下的主机（兼容既有全量调用）。
    """
    with get_connection() as conn:
        if case_id is not None:
            row = conn.execute(
                "SELECT "
                "  (SELECT COUNT(*) FROM hosts WHERE case_id=?) as total, "
                "  (SELECT COUNT(*) FROM hosts h LEFT JOIN agents a ON h.id = a.host_id "
                "    WHERE h.case_id=? AND a.last_heartbeat > datetime('now', ?)) as online, "
                "  (SELECT COUNT(*) FROM hosts h LEFT JOIN agents a ON h.id = a.host_id "
                "    WHERE h.case_id=? AND (a.last_heartbeat IS NULL OR a.last_heartbeat <= datetime('now', ?))) as offline ",
                (case_id, case_id, f'-{_ONLINE_WINDOW_SECONDS} seconds',
                 case_id, f'-{_ONLINE_WINDOW_SECONDS} seconds'),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT "
                "  (SELECT COUNT(*) FROM hosts) as total, "
                "  (SELECT COUNT(*) FROM hosts h LEFT JOIN agents a ON h.id = a.host_id "
                "    WHERE a.last_heartbeat > datetime('now', ?)) as online, "
                "  (SELECT COUNT(*) FROM hosts h LEFT JOIN agents a ON h.id = a.host_id "
                "    WHERE a.last_heartbeat IS NULL OR a.last_heartbeat <= datetime('now', ?)) as offline ",
                (f'-{_ONLINE_WINDOW_SECONDS} seconds', f'-{_ONLINE_WINDOW_SECONDS} seconds'),
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
