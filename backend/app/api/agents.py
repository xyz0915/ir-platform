"""Agent 注册/心跳/断开 API + 主机在线状态."""
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

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


@router.get("/hosts/online")
def online_hosts(timeout: int = Query(90), current_user: dict = Depends(get_current_user)):
    """获取在线主机列表."""
    hosts = AgentModel.get_online_hosts(timeout_seconds=timeout)
    return {"success": True, "data": hosts}


@router.get("/hosts/online-status")
def all_hosts_status(timeout: int = Query(90), current_user: dict = Depends(get_current_user)):
    """获取所有主机的在线/离线状态."""
    hosts = AgentModel.get_all_with_status(timeout_seconds=timeout)
    return {"success": True, "data": hosts}
