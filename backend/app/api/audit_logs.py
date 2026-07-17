"""审计日志 API — 审计日志查询与清理."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.database import get_connection
from app.services.auth_service import get_current_user
from app.services.audit_service import create_audit_log

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("")
def list_audit_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    user_id: Optional[int] = Query(None),
    action_type: Optional[str] = Query(None),
    start_time: Optional[str] = Query(None),
    end_time: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """获取审计日志列表（分页 + 筛选）."""
    conditions = []
    params = []

    if user_id is not None:
        conditions.append("user_id = ?")
        params.append(user_id)
    if action_type:
        conditions.append("action_type = ?")
        params.append(action_type)
    if start_time:
        conditions.append("created_at >= ?")
        params.append(start_time)
    if end_time:
        conditions.append("created_at <= ?")
        params.append(end_time)

    where = ""
    if conditions:
        where = "WHERE " + " AND ".join(conditions)

    offset = (page - 1) * page_size

    with get_connection() as conn:
        count_row = conn.execute(
            f"SELECT COUNT(*) as cnt FROM audit_logs {where}", params
        ).fetchone()
        total = count_row["cnt"] if count_row else 0

        rows = conn.execute(
            f"SELECT id, user_id, username, action_type, detail, target_type, target_id, ip_address, created_at "
            f"FROM audit_logs {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [page_size, offset],
        ).fetchall()

    items = [dict(r) for r in rows]
    return {"code": 0, "data": {"total": total, "items": items}, "message": "success"}


@router.get("/action-types")
def list_action_types(
    current_user: dict = Depends(get_current_user),
):
    """获取审计日志操作类型列表."""
    return {
        "code": 0,
        "data": [
            "login",
            "logout",
            "rule_change",
            "event_dispose",
            "ai_analysis",
            "settings_change",
            "user_manage",
        ],
        "message": "success",
    }


@router.delete("/cleanup")
def cleanup_audit_logs(
    current_user: dict = Depends(get_current_user),
):
    """清理过期审计日志（根据 system_settings 中的 log_retention_days）. """
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可执行清理")

    with get_connection() as conn:
        setting = conn.execute(
            "SELECT value FROM system_settings WHERE key = 'log_retention_days'"
        ).fetchone()
        retention_days = int(setting["value"]) if setting else 90

        deleted = conn.execute(
            "DELETE FROM audit_logs WHERE created_at < datetime('now', ?)",
            (f"-{retention_days} days",),
        ).rowcount
        conn.commit()

    create_audit_log(
        user_id=current_user["id"],
        username=current_user["username"],
        action_type="settings_change",
        detail=f"清理过期审计日志: 删除 {deleted} 条记录（保留 {retention_days} 天）",
    )
    return {"code": 0, "data": {"deleted": deleted, "retention_days": retention_days}, "message": "success"}
