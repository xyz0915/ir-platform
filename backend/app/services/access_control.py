"""ACL 权限服务 — 角色判定 + 案件级授权 + 主机级派生（P0-2）。

模型：用户对案件授权（``user_case_access``），可见主机 = 授权案件下所有主机
（``hosts.case_id`` 已存在，无需给 hosts 加列）。admin 角色绕过 ACL（全量
可见），兼容存量演示账号。

设计约束（§1）：
- 参数化查询防注入是硬红线：集合一律 ``?`` 绑定，绝不拼接用户输入。
- 显式资源访问（单条/写操作）→ 越权直接 403（fail fast）；
  列表/检索类 → 静默注入可见集合（空集合 → WHERE 1=0 返回空）。
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException

from app.config import settings
from app.database import get_connection
from app.services.audit_service import create_audit_log

logger = logging.getLogger(__name__)

ROLE_ADMIN = "admin"
CASE_ROLE_OWNER = "owner"
CASE_ROLE_ANALYST = "analyst"
CASE_ROLE_VIEWER = "viewer"
CASE_ROLES = (CASE_ROLE_OWNER, CASE_ROLE_ANALYST, CASE_ROLE_VIEWER)

# role 等级（用于 >= 比较）
_ROLE_RANK = {CASE_ROLE_VIEWER: 1, CASE_ROLE_ANALYST: 2, CASE_ROLE_OWNER: 3}


def is_admin(user: dict) -> bool:
    """user.role == 'admin'（缺失按 admin 兼容）。"""
    return (user or {}).get("role", "admin") == ROLE_ADMIN


def acl_strict_mode() -> bool:
    """读取 ACL 严格模式开关（环境变量优先，system_settings 兜底，默认 on）。

    - 环境变量 IR_ACL_STRICT_MODE 显式设置时最高优先级；
    - 否则读取 system_settings.acl_strict_mode（运维可通过设置 API 运行时切换）；
    - 均未设置 → 默认 True（最小权限）。

    Returns:
        True=非 admin 强制过滤（默认）；False=保留旧行为（全量可见）。
    """
    import os as _os

    env_raw = _os.environ.get("IR_ACL_STRICT_MODE")
    if env_raw is not None:
        return env_raw.strip().lower() in ("1", "true", "yes", "on")
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT value FROM system_settings WHERE key = 'acl_strict_mode'"
            ).fetchone()
        if row is not None:
            return str(row["value"]).strip().lower() in ("1", "true", "yes", "on")
    except Exception as exc:  # noqa: BLE001
        logger.debug("acl_strict_mode read failed, default on: %s", exc)
    return True


def get_visible_case_ids(user: dict) -> Optional[set[int]]:
    """admin → None（全量）；非 admin → user_case_access 中授权的 case_id 集合。"""
    if is_admin(user):
        return None
    user_id = (user or {}).get("id")
    if user_id is None:
        return set()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT case_id FROM user_case_access WHERE user_id = ?",
            (user_id,),
        ).fetchall()
    return {r["case_id"] for r in rows}


def get_visible_host_ids(user: dict) -> Optional[set[int]]:
    """admin → None（全量）；非 admin → SELECT id FROM hosts WHERE case_id IN 授权案件。"""
    case_ids = get_visible_case_ids(user)
    if case_ids is None:
        return None
    if not case_ids:
        return set()
    placeholders = ",".join("?" for _ in case_ids)
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT id FROM hosts WHERE case_id IN ({placeholders})",
            sorted(case_ids),
        ).fetchall()
    return {r["id"] for r in rows}


def _get_role_in_case(user_id: Optional[int], case_id: int) -> Optional[str]:
    """查询用户在某案件的角色（无授权返回 None）。"""
    if user_id is None:
        return None
    with get_connection() as conn:
        row = conn.execute(
            "SELECT role_in_case FROM user_case_access WHERE user_id = ? AND case_id = ?",
            (user_id, case_id),
        ).fetchone()
    return row["role_in_case"] if row else None


def require_case_access(user: dict, case_id: int, min_role: str = CASE_ROLE_VIEWER) -> None:
    """admin 直接通过；否则校验 user_case_access.role_in_case >= min_role，失败 403。"""
    if is_admin(user):
        return
    if not acl_strict_mode():
        return
    role = _get_role_in_case((user or {}).get("id"), case_id)
    if role is None:
        raise HTTPException(status_code=403, detail="无权访问该案件")
    if _ROLE_RANK.get(role, 0) < _ROLE_RANK.get(min_role, 1):
        raise HTTPException(status_code=403, detail=f"需要更高案件角色: {min_role}")


def require_host_access(user: dict, host_id: int, min_role: str = CASE_ROLE_VIEWER) -> None:
    """解析 host.case_id → require_case_access；host 不存在 → 404。"""
    if is_admin(user):
        return
    if not acl_strict_mode():
        return
    with get_connection() as conn:
        row = conn.execute("SELECT case_id FROM hosts WHERE id = ?", (host_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"主机不存在: id={host_id}")
    require_case_access(user, row["case_id"], min_role=min_role)


def resolve_allowed_host_ids(
    user: dict,
    requested_host_id: Optional[int] = None,
) -> Optional[set[int]]:
    """解析允许查询的主机集合。

    - admin → None（全量，不加过滤）
    - 非 admin：requested 为空 → 可见全集；requested 越权 → 403；否则 {requested}
    """
    if is_admin(user):
        return None
    if not acl_strict_mode():
        return None
    visible = get_visible_host_ids(user) or set()
    if requested_host_id is not None:
        require_host_access(user, requested_host_id)
        return {requested_host_id}
    return visible


def grant_case_access(operator: dict, user_id: int, case_id: int, role_in_case: str) -> dict:
    """授权（仅 admin 可调用）。写操作记 audit_logs(action_type='acl_grant')。"""
    if not is_admin(operator):
        raise HTTPException(status_code=403, detail="仅管理员可管理授权")
    if role_in_case not in CASE_ROLES:
        raise HTTPException(status_code=400, detail=f"role_in_case 必须是 {', '.join(CASE_ROLES)}")
    with get_connection() as conn:
        user_row = conn.execute(
            "SELECT id, username FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if user_row is None:
            raise HTTPException(status_code=404, detail="用户不存在")
        case_row = conn.execute(
            "SELECT id, name FROM cases WHERE id = ?", (case_id,)
        ).fetchone()
        if case_row is None:
            raise HTTPException(status_code=404, detail="案件不存在")
        conn.execute(
            """
            INSERT INTO user_case_access (user_id, case_id, role_in_case, granted_by, granted_at)
            VALUES (?, ?, ?, ?, datetime('now'))
            ON CONFLICT(user_id, case_id) DO UPDATE SET
                role_in_case = excluded.role_in_case,
                granted_by = excluded.granted_by,
                granted_at = datetime('now')
            """,
            (user_id, case_id, role_in_case, operator.get("id")),
        )
        conn.commit()
    create_audit_log(
        user_id=operator.get("id"),
        username=operator.get("username", ""),
        action_type="acl_grant",
        detail=(
            f"授权用户 {user_row['username']}(id={user_id}) "
            f"案件 {case_row['name']}(id={case_id}) 角色={role_in_case}"
        ),
        target_type="user",
        target_id=str(user_id),
    )
    return {"user_id": user_id, "case_id": case_id, "role_in_case": role_in_case}


def revoke_case_access(operator: dict, user_id: int, case_id: int) -> None:
    """撤销授权（仅 admin 可调用）。写操作记 audit_logs(action_type='acl_revoke')。"""
    if not is_admin(operator):
        raise HTTPException(status_code=403, detail="仅管理员可管理授权")
    with get_connection() as conn:
        user_row = conn.execute(
            "SELECT id, username FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if user_row is None:
            raise HTTPException(status_code=404, detail="用户不存在")
        conn.execute(
            "DELETE FROM user_case_access WHERE user_id = ? AND case_id = ?",
            (user_id, case_id),
        )
        conn.commit()
    create_audit_log(
        user_id=operator.get("id"),
        username=operator.get("username", ""),
        action_type="acl_revoke",
        detail=f"撤销用户 {user_row['username']}(id={user_id}) 案件授权 case_id={case_id}",
        target_type="user",
        target_id=str(user_id),
    )


def list_user_grants(user_id: int) -> list[dict]:
    """列出用户的案件授权（仅 admin 可调用）。"""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT uca.case_id, uca.role_in_case, uca.granted_by, uca.granted_at,
                   c.name AS case_name, c.case_number
            FROM user_case_access uca
            LEFT JOIN cases c ON c.id = uca.case_id
            WHERE uca.user_id = ?
            ORDER BY uca.case_id
            """,
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]
