"""系统参数 API — 获取/更新系统配置."""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.database import get_connection
from app.services.auth_service import get_current_user
from app.services.audit_service import create_audit_log

logger = logging.getLogger(__name__)
router = APIRouter()


class UpdateSettingRequest(BaseModel):
    value: str


@router.get("")
def get_all_settings(
    current_user: dict = Depends(get_current_user),
):
    """获取所有系统参数."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT key, value, description, value_type, updated_at FROM system_settings ORDER BY key"
        ).fetchall()

    items = [dict(r) for r in rows]
    return {"code": 0, "data": items, "message": "success"}


@router.put("/{key}")
def update_setting(
    key: str,
    data: UpdateSettingRequest,
    current_user: dict = Depends(get_current_user),
):
    """更新指定系统参数."""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可修改系统参数")

    with get_connection() as conn:
        setting = conn.execute(
            "SELECT key, value_type FROM system_settings WHERE key = ?", (key,)
        ).fetchone()
        if not setting:
            raise HTTPException(status_code=404, detail="参数不存在")

        value_type = setting["value_type"]
        new_value = data.value

        # 类型校验
        if value_type == "bool":
            if new_value not in ("true", "false"):
                raise HTTPException(status_code=400, detail="bool 类型只接受 true/false")
        elif value_type == "int":
            try:
                int(new_value)
            except (ValueError, TypeError):
                raise HTTPException(status_code=400, detail="int 类型需为有效整数")

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute(
            "UPDATE system_settings SET value = ?, updated_at = ? WHERE key = ?",
            (new_value, now, key),
        )
        conn.commit()

    create_audit_log(
        user_id=current_user["id"],
        username=current_user["username"],
        action_type="settings_change",
        detail=f"更新系统参数: {key}={new_value}",
        target_type="system_settings",
        target_id=key,
    )
    return {"code": 0, "data": {"key": key, "value": new_value}, "message": "success"}


@router.get("/deployment")
def get_deployment(current_user: dict = Depends(get_current_user)):
    """获取部署配置（F14 / M9）。返回 DeploymentConfig（对齐 01-api-spec.md §9.1）。

    - stateless_enabled ← app.config.settings.STATELESS_MODE 标志
    - redis_connected    ← 运行时 redis ping（缺失/未配置默认 false）
    - sse_protocol / hitl_protocol ← 常量（Orchestrator 统一协议）
    """
    redis_connected = False
    try:
        import redis  # 可选依赖（MVP 未引入，缺失则保持 false）

        redis_url = getattr(settings, "REDIS_URL", None)
        if redis_url:
            client = redis.Redis.from_url(redis_url, socket_connect_timeout=1)
            redis_connected = bool(client.ping())
    except Exception:
        redis_connected = False

    return {
        "code": 0,
        "data": {
            "stateless_enabled": bool(getattr(settings, "STATELESS_MODE", False)),
            "redis_connected": redis_connected,
            "sse_protocol": "step_* (Orchestrator 统一)",
            "hitl_protocol": "hitl_approval + resume",
        },
        "message": "success",
    }
