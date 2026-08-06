"""export_audit_log 数据模型 — 导出审计表 CRUD（P0-4）。"""

import json
import logging
from typing import Any, Optional

from app.database import get_connection

logger = logging.getLogger(__name__)


class ExportAuditLog:
    """导出审计表 CRUD。"""

    @staticmethod
    def create(
        user_id: Optional[int],
        username: str,
        case_id: Optional[int] = None,
        host_ids: Optional[list[int]] = None,
        query_params: Any = None,
        row_count: int = 0,
        format: str = "json",
        masked: int = 0,
        ip_address: str = "",
    ) -> int:
        """写入一条导出审计记录，返回主键 id。

        Args:
            user_id: 操作用户 ID（可空）。
            username: 操作用户名。
            case_id: 关联案件 ID（可空）。
            host_ids: 实际生效的可见主机 ID 列表。
            query_params: 导出参数快照（dict，自动 JSON 序列化）。
            row_count: 导出行数。
            format: json | csv。
            masked: 是否脱敏（1/0）。
            ip_address: 客户端 IP。
        """
        host_ids_json = json.dumps(host_ids or [], ensure_ascii=False, default=str)
        params_json = json.dumps(query_params or {}, ensure_ascii=False, default=str)
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO export_audit_log
                (user_id, username, case_id, host_ids, query_params, row_count,
                 format, masked, ip_address, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (user_id, username, case_id, host_ids_json, params_json,
                 row_count, format, masked, ip_address),
            )
            aid = cursor.lastrowid
            conn.commit()
        return aid

    @staticmethod
    def list_all(
        user_id: Optional[int] = None,
        format: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        """分页列出导出审计（admin 用）。

        Returns:
            {items, total, page, page_size}。
        """
        conditions: list[str] = []
        params: list[Any] = []
        if user_id is not None:
            conditions.append("user_id = ?")
            params.append(user_id)
        if format:
            conditions.append("format = ?")
            params.append(format)
        if date_from:
            conditions.append("created_at >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("created_at <= ?")
            params.append(date_to)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        with get_connection() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM export_audit_log {where}", params
            ).fetchone()[0]
            offset = (page - 1) * page_size
            rows = conn.execute(
                f"SELECT * FROM export_audit_log {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                params + [page_size, offset],
            ).fetchall()
        return {
            "items": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
