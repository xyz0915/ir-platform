"""同步服务 API（v2 SyncLayer 接口）.

端点:
  POST /api/sync/host/{host_id}          — 触发 CM→AC 同步
  POST /api/sync/backfill/{host_id}      — 全量补同步
  POST /api/sync/event/{event_uid}       — AC→CM 单事件处置回写
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.services.auth_service import get_current_user
from app.services.sync_service import SyncService

router = APIRouter()


@router.post("/host/{host_id}")
def sync_host(
    host_id: int,
    current_user: dict = Depends(get_current_user),
):
    """CM→AC 同步：将 CM 分析结果（行为告警/持久化/融合检测）写入 security_events。"""
    result = SyncService.sync_cm_to_ac(host_id)
    return {"code": 0, "data": result, "message": "success"}


@router.post("/backfill/{host_id}")
def sync_backfill(
    host_id: int,
    current_user: dict = Depends(get_current_user),
):
    """全量补同步（CM→AC + AC→CM），首次接入或修复后使用。"""
    result = SyncService.backfill(host_id, source="cm")
    return {"code": 0, "data": result, "message": "success"}


@router.post("/event/{event_uid}")
def sync_event(
    event_uid: str,
    current_user: dict = Depends(get_current_user),
):
    """AC→CM 回写：将 AC 侧状态/处置变更同步回 CM。"""
    result = SyncService.sync_ac_to_cm(event_uid)
    return {"code": 0, "data": result, "message": "success"}
