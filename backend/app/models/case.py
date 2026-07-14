"""Case 数据模型 — 案件 CRUD 操作."""

import logging
from typing import Any, Optional

from app.database import get_connection

logger = logging.getLogger(__name__)


class Case:
    """案件数据模型."""

    @staticmethod
    def create(name: str, case_number: Optional[str] = None,
               description: Optional[str] = None,
               priority: Optional[str] = None) -> dict:
        """创建案件.

        Args:
            name: 案件名称.
            case_number: 案件编号（唯一）.
            description: 案件描述.
            priority: 优先级.

        Returns:
            新创建的案件字典.
        """
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO cases (name, case_number, description, status, priority)
                VALUES (?, ?, ?, 'open', COALESCE(?, 'medium'))
                """,
                (name, case_number, description, priority),
            )
            case_id = cursor.lastrowid
        # Transaction committed after with block exits; query on a fresh connection
        return Case.get_by_id(case_id)

    @staticmethod
    def get_by_id(case_id: int) -> Optional[dict]:
        """根据 ID 获取案件."""
        with get_connection() as conn:
            row = conn.execute(
                """SELECT c.*,
                          COALESCE((SELECT COUNT(*) FROM hosts WHERE case_id = c.id), 0) AS host_count,
                          COALESCE((SELECT SUM(item_count) FROM agent_imports WHERE host_id IN (SELECT id FROM hosts WHERE case_id = c.id)), 0) AS log_count
                     FROM cases c WHERE c.id = ?""",
                (case_id,),
            ).fetchone()
            return dict(row) if row else None

    @staticmethod
    def list(page: int = 1, size: int = 20, search: str = "") -> dict:
        """获取案件列表（分页 + 搜索）.

        Returns:
            {"items": [...], "total": N}
        """
        offset = (page - 1) * size
        # 统一查询：LEFT JOIN 聚合 host_count + log_count
        base_sql = """
            SELECT c.*,
                   COALESCE((SELECT COUNT(*) FROM hosts WHERE case_id = c.id), 0) AS host_count,
                   COALESCE((SELECT SUM(item_count) FROM agent_imports WHERE host_id IN (SELECT id FROM hosts WHERE case_id = c.id)), 0) AS log_count
            FROM cases c
        """
        with get_connection() as conn:
            if search:
                like = f"%{search}%"
                total = conn.execute(
                    "SELECT COUNT(*) as cnt FROM cases WHERE name LIKE ? OR case_number LIKE ?",
                    (like, like),
                ).fetchone()["cnt"]
                rows = conn.execute(
                    f"""{base_sql}
                       WHERE c.name LIKE ? OR c.case_number LIKE ?
                       ORDER BY c.created_at DESC LIMIT ? OFFSET ?""",
                    (like, like, size, offset),
                ).fetchall()
            else:
                total = conn.execute(
                    "SELECT COUNT(*) as cnt FROM cases"
                ).fetchone()["cnt"]
                rows = conn.execute(
                    f"{base_sql} ORDER BY c.created_at DESC LIMIT ? OFFSET ?",
                    (size, offset),
                ).fetchall()
            return {"items": [dict(r) for r in rows], "total": total}

    @staticmethod
    def update(case_id: int, name: Optional[str] = None,
               description: Optional[str] = None,
               status: Optional[str] = None,
               priority: Optional[str] = None) -> Optional[dict]:
        """更新案件信息."""
        with get_connection() as conn:
            fields = []
            params: list = []
            if name is not None:
                fields.append("name = ?")
                params.append(name)
            if description is not None:
                fields.append("description = ?")
                params.append(description)
            if status is not None:
                fields.append("status = ?")
                params.append(status)
            if priority is not None:
                fields.append("priority = ?")
                params.append(priority)
            if fields:
                fields.append("updated_at = datetime('now')")
                params.append(case_id)
                conn.execute(
                    f"UPDATE cases SET {', '.join(fields)} WHERE id = ?",
                    params,
                )
        # Transaction committed after with block exits; query on a fresh connection
        return Case.get_by_id(case_id)

    @staticmethod
    def delete(case_id: int) -> bool:
        """删除案件."""
        with get_connection() as conn:
            conn.execute("DELETE FROM cases WHERE id = ?", (case_id,))
            return True
