"""白名单数据模型 — whitelist 表的 CRUD 操作."""

import json
import logging
from typing import Any, Optional

from app.database import get_connection

logger = logging.getLogger(__name__)


class WhitelistModel:
    """白名单模型.

    提供 whitelist 表的 CRUD 操作：batch_create / list_all / get_by_id / delete_by_id / delete_all.
    """

    @staticmethod
    def batch_create(items: list) -> int:
        """批量创建白名单记录.

        Args:
            items: 白名单项列表，每项需包含 category, pattern, source, description, enabled 字段.

        Returns:
            插入的记录数.
        """
        if not items:
            return 0
        with get_connection() as conn:
            count = 0
            for item in items:
                conn.execute(
                    """
                    INSERT INTO whitelist (category, pattern, source, description, enabled)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        item.get("category", "path"),
                        item.get("pattern", ""),
                        item.get("source", "user"),
                        item.get("description", ""),
                        1 if item.get("enabled", True) else 0,
                    ),
                )
                count += 1
            return count

    @staticmethod
    def list_all(category: Optional[str] = None) -> list:
        """获取白名单列表.

        Args:
            category: 按类别筛选（可选），支持 'path' / 'process_name' / 'signature'.

        Returns:
            白名单项列表.
        """
        with get_connection() as conn:
            if category:
                rows = conn.execute(
                    "SELECT * FROM whitelist WHERE category = ? ORDER BY id ASC",
                    (category,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM whitelist ORDER BY category, id ASC"
                ).fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def get_by_id(id: int) -> Optional[dict]:
        """按 ID 获取白名单项.

        Args:
            id: 白名单项 ID.

        Returns:
            白名单项字典，不存在时返回 None.
        """
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM whitelist WHERE id = ?", (id,)
            ).fetchone()
            return dict(row) if row else None

    @staticmethod
    def delete_by_id(id: int) -> bool:
        """按 ID 删除白名单项.

        Args:
            id: 白名单项 ID.

        Returns:
            是否删除成功.
        """
        with get_connection() as conn:
            cursor = conn.execute("DELETE FROM whitelist WHERE id = ?", (id,))
            return cursor.rowcount > 0

    @staticmethod
    def delete_all() -> None:
        """删除所有白名单项."""
        with get_connection() as conn:
            conn.execute("DELETE FROM whitelist")
