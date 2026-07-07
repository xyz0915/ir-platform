"""User 数据模型 — 用户 CRUD."""

import logging
from typing import Any, Optional

from app.database import get_connection

logger = logging.getLogger(__name__)


class User:
    """用户数据模型."""

    @staticmethod
    def get_by_username(username: str) -> Optional[dict]:
        """根据用户名获取用户."""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE username = ?", (username,)
            ).fetchone()
            return dict(row) if row else None

    @staticmethod
    def get_by_id(user_id: int) -> Optional[dict]:
        """根据 ID 获取用户."""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            return dict(row) if row else None

    @staticmethod
    def create(username: str, password_hash: str, role: str = "admin") -> dict:
        """创建用户."""
        with get_connection() as conn:
            cursor = conn.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                (username, password_hash, role),
            )
            user_id = cursor.lastrowid
        # Transaction committed after with block exits; query on a fresh connection
        return User.get_by_id(user_id)

    @staticmethod
    def update_password(user_id: int, password_hash: str) -> bool:
        """更新用户密码."""
        with get_connection() as conn:
            conn.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (password_hash, user_id),
            )
            return True
