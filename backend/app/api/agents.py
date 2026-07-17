"""Agent 注册/心跳/断开 API + 主机在线状态."""
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from app.database import get_connection
from app.models.agent_model import AgentModel
from app.services.auth_service import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()


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
