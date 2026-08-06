"""用户管理 API — 用户 CRUD、密码重置、启用/禁用."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.database import get_connection
from app.services.auth_service import get_current_user, hash_password
from app.services.audit_service import create_audit_log
from app.services.access_control import (
    grant_case_access,
    revoke_case_access,
    list_user_grants,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ─── 请求/响应模型 ─────────────────────────────────────────────


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str = "analyst"
    display_name: Optional[str] = None


class UpdateUserRequest(BaseModel):
    display_name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[int] = None


class ResetPasswordRequest(BaseModel):
    new_password: str


class GrantAccessRequest(BaseModel):
    case_id: int
    role_in_case: str = "viewer"


# ─── API 端点 ─────────────────────────────────────────────────


@router.get("/users")
def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    """获取用户列表（分页）."""
    offset = (page - 1) * page_size
    with get_connection() as conn:
        count_row = conn.execute("SELECT COUNT(*) as cnt FROM users").fetchone()
        total = count_row["cnt"] if count_row else 0

        rows = conn.execute(
            "SELECT id, username, display_name, role, is_active, last_login, created_at "
            "FROM users ORDER BY id ASC LIMIT ? OFFSET ?",
            (page_size, offset),
        ).fetchall()

    items = [dict(r) for r in rows]
    return {"code": 0, "data": {"total": total, "items": items}, "message": "success"}


@router.post("/users")
def create_user(
    data: CreateUserRequest,
    current_user: dict = Depends(get_current_user),
):
    """新增用户."""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可创建用户")

    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM users WHERE username = ?", (data.username,)
        ).fetchone()
        if existing:
            raise HTTPException(status_code=400, detail="用户名已存在")

        password_hash = hash_password(data.password)
        cursor = conn.execute(
            "INSERT INTO users (username, password_hash, role, display_name) VALUES (?, ?, ?, ?)",
            (data.username, password_hash, data.role, data.display_name),
        )
        new_id = cursor.lastrowid
        conn.commit()

    create_audit_log(
        user_id=current_user["id"],
        username=current_user["username"],
        action_type="user_manage",
        detail=f"创建用户: {data.username}",
        target_type="user",
        target_id=str(new_id),
    )
    return {"code": 0, "data": {"id": new_id}, "message": "success"}


@router.put("/users/{user_id}")
def update_user(
    user_id: int,
    data: UpdateUserRequest,
    current_user: dict = Depends(get_current_user),
):
    """编辑用户信息."""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可编辑用户")

    with get_connection() as conn:
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")

        updates = []
        params = []
        if data.display_name is not None:
            updates.append("display_name = ?")
            params.append(data.display_name)
        if data.role is not None:
            updates.append("role = ?")
            params.append(data.role)
        if data.is_active is not None:
            updates.append("is_active = ?")
            params.append(data.is_active)

        if updates:
            params.append(user_id)
            conn.execute(
                f"UPDATE users SET {', '.join(updates)} WHERE id = ?",
                params,
            )
            conn.commit()

    create_audit_log(
        user_id=current_user["id"],
        username=current_user["username"],
        action_type="user_manage",
        detail=f"编辑用户 ID={user_id}",
        target_type="user",
        target_id=str(user_id),
    )
    return {"code": 0, "data": {"id": user_id}, "message": "success"}


@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    current_user: dict = Depends(get_current_user),
):
    """删除用户（不能删除最后一个管理员）."""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可删除用户")

    with get_connection() as conn:
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")

        if user["role"] == "admin":
            admin_count = conn.execute(
                "SELECT COUNT(*) as cnt FROM users WHERE role = 'admin'"
            ).fetchone()
            if admin_count and admin_count["cnt"] <= 1:
                raise HTTPException(status_code=400, detail="不能删除最后一个管理员")

        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()

    create_audit_log(
        user_id=current_user["id"],
        username=current_user["username"],
        action_type="user_manage",
        detail=f"删除用户: {user['username']}",
        target_type="user",
        target_id=str(user_id),
    )
    return {"code": 0, "data": {"id": user_id}, "message": "success"}


@router.post("/users/{user_id}/reset-password")
def reset_password(
    user_id: int,
    data: ResetPasswordRequest,
    current_user: dict = Depends(get_current_user),
):
    """重置用户密码."""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可重置密码")

    with get_connection() as conn:
        user = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")

        password_hash = hash_password(data.new_password)
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (password_hash, user_id),
        )
        conn.commit()

    create_audit_log(
        user_id=current_user["id"],
        username=current_user["username"],
        action_type="user_manage",
        detail=f"重置用户密码 ID={user_id}",
        target_type="user",
        target_id=str(user_id),
    )
    return {"code": 0, "data": {"id": user_id}, "message": "success"}


@router.post("/users/{user_id}/toggle-active")
def toggle_user_active(
    user_id: int,
    current_user: dict = Depends(get_current_user),
):
    """启用/禁用用户."""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可操作")

    with get_connection() as conn:
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")

        new_active = 0 if user["is_active"] else 1
        conn.execute(
            "UPDATE users SET is_active = ? WHERE id = ?",
            (new_active, user_id),
        )
        conn.commit()

    status_text = "启用" if new_active else "禁用"
    create_audit_log(
        user_id=current_user["id"],
        username=current_user["username"],
        action_type="user_manage",
        detail=f"{status_text}用户: {user['username']}",
        target_type="user",
        target_id=str(user_id),
    )
    return {"code": 0, "data": {"id": user_id, "is_active": new_active}, "message": "success"}


# ─── P0-2 ACL 授权管理（admin only）────────────────────────────


@router.get("/users/{user_id}/access")
def list_user_case_access(
    user_id: int,
    current_user: dict = Depends(get_current_user),
):
    """列出用户的案件授权（仅 admin）。"""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可管理授权")
    with get_connection() as conn:
        user = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
    grants = list_user_grants(user_id)
    return {"code": 0, "data": {"user_id": user_id, "items": grants}, "message": "success"}


@router.post("/users/{user_id}/access")
def grant_user_case_access(
    user_id: int,
    data: GrantAccessRequest,
    current_user: dict = Depends(get_current_user),
):
    """授权用户访问案件（仅 admin）。

    Body: {"case_id": 1, "role_in_case": "viewer|analyst|owner"}
    """
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可管理授权")
    result = grant_case_access(
        operator=current_user,
        user_id=user_id,
        case_id=data.case_id,
        role_in_case=data.role_in_case,
    )
    return {"code": 0, "data": result, "message": "success"}


@router.delete("/users/{user_id}/access/{case_id}")
def revoke_user_case_access(
    user_id: int,
    case_id: int,
    current_user: dict = Depends(get_current_user),
):
    """撤销用户对案件的访问授权（仅 admin）。"""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可管理授权")
    revoke_case_access(operator=current_user, user_id=user_id, case_id=case_id)
    return {"code": 0, "data": {"user_id": user_id, "case_id": case_id}, "message": "success"}
