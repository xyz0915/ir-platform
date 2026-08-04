"""长期记忆 API（P2：agent_memories）.

挂载于前缀 ``/api/memories``（main.py 统一注册，**不在本文件重复前缀**），
所有端点均经 ``Depends(get_current_user)`` 鉴权。统一信封 ``{code, data, message}``。

端点：
- ``GET    /api/memories``          列表/筛选/分页（含 q 关键词）
- ``GET    /api/memories/search``   关键词检索（q 必填，供记忆引用/前端检索框）
- ``POST   /api/memories``          手动写入（content 必填，created_by=当前用户）
- ``DELETE /api/memories/{id}``     删除（不存在 404 兜底）
"""

import logging
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status as http_status

from app.models.agent_memory import AgentMemory
from app.services.auth_service import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("")
def list_memories(
    event_id: Optional[str] = Query(None, description="按事件过滤"),
    host_id: Optional[int] = Query(None, description="按主机过滤"),
    agent_name: Optional[str] = Query(None, description="按来源智能体过滤"),
    memory_type: Optional[str] = Query(None, description="按类型过滤：conclusion|summary|action|disposition"),
    q: Optional[str] = Query(None, description="对 content/tags 关键词过滤"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(50, ge=1, le=200, description="每页条数"),
    current_user: dict = Depends(get_current_user),
):
    """列出长期记忆（支持筛选/关键词/分页）."""
    try:
        result = AgentMemory.list(
            event_id=event_id,
            host_id=host_id,
            agent_name=agent_name,
            memory_type=memory_type,
            q=q,
            page=page,
            page_size=page_size,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("列出记忆失败: %s", exc)
        return {"code": -1, "data": {"items": [], "total": 0}, "message": str(exc)}
    return {"code": 0, "data": result, "message": "success"}


@router.get("/search")
def search_memories(
    q: str = Query(..., min_length=1, description="关键词（必填）"),
    event_id: Optional[str] = Query(None, description="按事件过滤"),
    host_id: Optional[int] = Query(None, description="按主机过滤"),
    agent_name: Optional[str] = Query(None, description="按来源智能体过滤"),
    memory_type: Optional[str] = Query(None, description="按类型过滤"),
    limit: int = Query(5, ge=1, le=20, description="返回条数上限（夹取 [1,20]）"),
    current_user: dict = Depends(get_current_user),
):
    """关键词检索长期记忆（供记忆引用 / 前端检索框）."""
    keyword = (q or "").strip()
    if not keyword:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST, detail="q 不能为空"
        )
    try:
        items = AgentMemory.search(
            q=keyword,
            event_id=event_id,
            host_id=host_id,
            agent_name=agent_name,
            memory_type=memory_type,
            limit=limit,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("检索记忆失败: %s", exc)
        return {"code": -1, "data": {"items": [], "total": 0}, "message": str(exc)}
    return {"code": 0, "data": {"items": items, "total": len(items)}, "message": "success"}


@router.post("")
def create_memory(
    payload: dict = Body(default={}),
    current_user: dict = Depends(get_current_user),
):
    """手动写入一条长期记忆.

    Body 字段：
        content: 必填，记忆正文（截断 IR_MEMORY_MAX_CONTENT）。
        memory_type: 可选，conclusion|summary|action|disposition（默认 summary）。
        event_id / host_id / agent_name / source_node: 可选关联信息。
        tags: 可选，标签数组。
        run_id: 可选，来源运行 ID（手动写入通常省略）。
    """
    content = (payload.get("content") or "").strip()
    if not content:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST, detail="content 不能为空"
        )
    memory_type = payload.get("memory_type") or "summary"
    if memory_type not in AgentMemory.TYPES:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=f"非法 memory_type: {memory_type}",
        )
    tags = payload.get("tags") or []
    if not isinstance(tags, list):
        tags = [tags]
    created_by = (current_user or {}).get("username") or "user"
    try:
        row = AgentMemory.create(
            run_id=payload.get("run_id"),
            event_id=payload.get("event_id"),
            host_id=payload.get("host_id"),
            agent_name=payload.get("agent_name") or "",
            memory_type=memory_type,
            content=content,
            source_node=payload.get("source_node") or "",
            tags=tags,
            created_by=created_by,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("写入记忆失败: %s", exc)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        )
    return {"code": 0, "data": row, "message": "success"}


@router.delete("/{memory_id}")
def delete_memory(
    memory_id: int,
    current_user: dict = Depends(get_current_user),
):
    """删除一条长期记忆；不存在返回 404 兜底."""
    deleted = AgentMemory.delete(memory_id)
    if not deleted:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="记忆不存在"
        )
    return {"code": 0, "data": {"deleted": True}, "message": "success"}
