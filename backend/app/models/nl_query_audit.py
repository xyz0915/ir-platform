"""NL 查询审计模型 — nl_query_audit 表 CRUD（§4.1 / §8.3）。"""

import json
import logging
from typing import Any, Optional

from app.database import get_connection

logger = logging.getLogger(__name__)


class NlQueryAudit:
    """NL 查询审计表 CRUD。"""

    @staticmethod
    def create(
        user_id: Optional[int] = None,
        nl_text: str = "",
        intent_json: Any = None,
        executed_sql_json: Any = None,
        row_count: int = 0,
        masked: int = 1,
        status: str = "ok",
        error_message: Optional[str] = None,
    ) -> int:
        """写入一条 NL 查询审计记录，返回主键 id。"""
        def _j(v: Any) -> str:
            if v is None:
                return "{}"
            if isinstance(v, (dict, list)):
                return json.dumps(v, ensure_ascii=False, default=str)
            return str(v)

        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO nl_query_audit
                (user_id, nl_text, intent_json, executed_sql_json, row_count,
                 masked, status, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, nl_text, _j(intent_json), _j(executed_sql_json),
                 row_count, masked, status, error_message),
            )
            aid = cursor.lastrowid
        return aid

    @staticmethod
    def get_by_id(aid: int) -> Optional[dict]:
        """按主键获取。"""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM nl_query_audit WHERE id = ?", (aid,)
            ).fetchone()
            return dict(row) if row else None

    @staticmethod
    def list_all(
        user_id: Optional[int] = None,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        """分页列出 NL 查询审计（admin 可按 user_id 过滤）。"""
        conditions = []
        params: list[Any] = []
        if user_id is not None:
            conditions.append("user_id = ?")
            params.append(user_id)
        if status:
            conditions.append("status = ?")
            params.append(status)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        with get_connection() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM nl_query_audit {where}", params
            ).fetchone()[0]
            offset = (page - 1) * page_size
            rows = conn.execute(
                f"SELECT * FROM nl_query_audit {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                params + [page_size, offset],
            ).fetchall()
        return {
            "items": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
