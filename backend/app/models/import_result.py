"""ImportResult 数据模型 — 日志导入结果明细 CRUD."""

import logging
from typing import Any, Optional

from app.database import get_connection

logger = logging.getLogger(__name__)


class ImportResult:
    """日志导入结果明细数据模型.

    对应 import_results 表，记录每一条解析出的日志事件。
    """

    @staticmethod
    def create(
        import_id: int,
        log_source: str,
        parsed_line: int,
        event_type: str,
        severity: str = "info",
        event_key_hash: Optional[str] = None,
    ) -> dict:
        """创建导入结果记录.

        Args:
            import_id: 关联的导入记录 ID.
            log_source: 日志来源（如 Security, System, Application）.
            parsed_line: 原始日志行号.
            event_type: 事件类型（如 4624, 4688）.
            severity: 严重级别，默认 'info'.
            event_key_hash: 事件去重哈希（可选）.

        Returns:
            dict: 新创建的导入结果记录.
        """
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO import_results
                    (import_id, log_source, parsed_line, event_type, severity, event_key_hash)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (import_id, log_source, parsed_line, event_type, severity, event_key_hash),
            )
            result_id = cursor.lastrowid
        return ImportResult.get_by_id(result_id)

    @staticmethod
    def get_by_id(result_id: int) -> Optional[dict]:
        """根据 ID 获取导入结果记录.

        Args:
            result_id: 导入结果记录 ID.

        Returns:
            dict | None: 导入结果记录字典，不存在则返回 None.
        """
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM import_results WHERE id = ?",
                (result_id,),
            ).fetchone()
            return dict(row) if row else None

    @staticmethod
    def list_by_import(import_id: int) -> list[dict[str, Any]]:
        """获取指定导入批次的所有结果明细.

        Args:
            import_id: 导入记录 ID.

        Returns:
            list[dict]: 导入结果记录列表，按 parsed_line 升序排列.
        """
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM import_results WHERE import_id = ? ORDER BY parsed_line ASC",
                (import_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def count_by_import(import_id: int) -> int:
        """统计指定导入批次的结果数量.

        Args:
            import_id: 导入记录 ID.

        Returns:
            int: 结果记录总数.
        """
        with get_connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM import_results WHERE import_id = ?",
                (import_id,),
            ).fetchone()
            return row["cnt"] if row else 0

    @staticmethod
    def delete_by_import(import_id: int) -> int:
        """删除指定导入批次的所有结果明细.

        Args:
            import_id: 导入记录 ID.

        Returns:
            int: 删除的记录数.
        """
        with get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM import_results WHERE import_id = ?",
                (import_id,),
            )
            deleted = cursor.rowcount
        logger.info("Deleted %d import_results for import_id=%d", deleted, import_id)
        return deleted
