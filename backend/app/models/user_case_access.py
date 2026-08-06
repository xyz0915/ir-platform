"""user_case_access 数据模型 — 用户→案件授权表 CRUD（P0-2）。"""

import logging
from typing import Optional

from app.database import get_connection

logger = logging.getLogger(__name__)


class UserCaseAccess:
    """用户→案件授权表 CRUD。"""

    @staticmethod
    def create(
        user_id: int,
        case_id: int,
        role_in_case: str = "viewer",
        granted_by: Optional[int] = None,
    ) -> dict:
        """插入授权（UPSERT 幂等，UNIQUE(user_id, case_id) 兜底）。

        Args:
            user_id: 目标用户 ID。
            case_id: 目标案件 ID。
            role_in_case: owner | analyst | viewer。
            granted_by: 授权操作人 ID（可为空）。

        Returns:
            授权记录字典。
        """
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO user_case_access (user_id, case_id, role_in_case, granted_by, granted_at)
                VALUES (?, ?, ?, ?, datetime('now'))
                ON CONFLICT(user_id, case_id) DO UPDATE SET
                    role_in_case = excluded.role_in_case,
                    granted_by = excluded.granted_by,
                    granted_at = datetime('now')
                """,
                (user_id, case_id, role_in_case, granted_by),
            )
            conn.commit()
        return UserCaseAccess.get_by_user_case(user_id, case_id)

    @staticmethod
    def get_by_user(user_id: int) -> list[dict]:
        """列出用户全部授权。"""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM user_case_access WHERE user_id = ? ORDER BY case_id",
                (user_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def get_by_user_case(user_id: int, case_id: int) -> Optional[dict]:
        """按用户+案件查询单条授权。"""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM user_case_access WHERE user_id = ? AND case_id = ?",
                (user_id, case_id),
            ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def delete(user_id: int, case_id: int) -> bool:
        """撤销授权；返回是否删除了行。"""
        with get_connection() as conn:
            cur = conn.execute(
                "DELETE FROM user_case_access WHERE user_id = ? AND case_id = ?",
                (user_id, case_id),
            )
            conn.commit()
            return cur.rowcount > 0

    @staticmethod
    def all_cases() -> list[dict]:
        """列出全部授权（管理用）。"""
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT uca.*, u.username, c.name AS case_name
                FROM user_case_access uca
                LEFT JOIN users u ON u.id = uca.user_id
                LEFT JOIN cases c ON c.id = uca.case_id
                ORDER BY uca.user_id, uca.case_id
                """
            ).fetchall()
        return [dict(r) for r in rows]
