"""MCP 工具 API — F7 工具/MCP 服务端（§2，MVP-1 只读聚合）.

注册：app.include_router(mcp.router, prefix="/api/mcp")。
真实 stdio/sse 调用属 MVP-2，本迭代仅提供只读聚合端点。

端点：
  GET /servers              列出 MCP 服务器状态（McpServer[]）
  GET /tools               列出全部工具定义（ToolDef[]）
  GET /servers/{id}/tools  按服务器列工具（ToolDef[]）
"""

import logging

from fastapi import APIRouter, Depends, HTTPException

from app.services.auth_service import get_current_user
from app.services.mcp.registry import ToolRegistry

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/servers")
def list_servers(user: dict = Depends(get_current_user)):
    """列出 MCP 服务器状态（transport/status/tools_count/last_heartbeat）。"""
    try:
        return {"code": 0, "data": ToolRegistry.list_servers(), "message": "success"}
    except Exception as exc:
        logger.exception("list_mcp_servers error")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/tools")
def list_tools(user: dict = Depends(get_current_user)):
    """列出全部工具定义（schema/idempotency_key/timeout/retries/category/status）。"""
    try:
        return {"code": 0, "data": ToolRegistry.list_tools(), "message": "success"}
    except Exception as exc:
        logger.exception("list_mcp_tools error")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/servers/{server_id:path}/tools")
def list_server_tools(server_id: str, user: dict = Depends(get_current_user)):
    """按服务器列出工具（McpServer[] → 该 server 的 ToolDef[]）。"""
    try:
        server = ToolRegistry.get_server(server_id)
        if not server:
            raise HTTPException(status_code=404, detail=f"MCP 服务器 {server_id} 不存在")
        return {
            "code": 0,
            "data": ToolRegistry.list_tools_by_server(server_id),
            "message": "success",
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("list_server_tools error")
        raise HTTPException(status_code=500, detail=str(exc))
