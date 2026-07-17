"""ImportRecord 数据模型 — 导入记录 CRUD."""

import logging
from typing import Any, Optional

from app.database import get_connection

logger = logging.getLogger(__name__)


class ImportRecord:
    """导入记录数据模型."""

    @staticmethod
    def create(host_id: int, file_name: str, file_path: str,
               status: str = "success", error_message: Optional[str] = None,
               data_summary: Optional[str] = None,
               log_type: Optional[str] = None,
               file_size: Optional[int] = None,
               parsed_count: Optional[int] = None,
               event_count: Optional[int] = None,
               task_id: Optional[str] = None) -> dict:
        """创建导入记录."""
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO import_records
                    (host_id, file_name, file_path, status, error_message, data_summary,
                     log_type, file_size, parsed_count, event_count, task_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (host_id, file_name, file_path, status, error_message, data_summary,
                 log_type, file_size, parsed_count, event_count, task_id),
            )
            record_id = cursor.lastrowid
        # Transaction committed after with block exits; query on a fresh connection
        return ImportRecord.get_by_id(record_id)

    @staticmethod
    def get_by_id(record_id: int) -> Optional[dict]:
        """根据 ID 获取导入记录."""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM import_records WHERE id = ?", (record_id,)
            ).fetchone()
            return dict(row) if row else None

    @staticmethod
    def list_by_host(host_id: int) -> list:
        """获取主机的所有导入记录."""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM import_records WHERE host_id = ? ORDER BY imported_at DESC",
                (host_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def update_status(record_id: int, status: str,
                      parsed_count: Optional[int] = None,
                      event_count: Optional[int] = None,
                      task_id: Optional[str] = None,
                      error_message: Optional[str] = None) -> dict:
        """更新导入记录的状态及进度信息."""
        with get_connection() as conn:
            updates = ["status=?"]
            params = [status]
            if parsed_count is not None:
                updates.append("parsed_count=?")
                params.append(parsed_count)
            if event_count is not None:
                updates.append("event_count=?")
                params.append(event_count)
            if task_id is not None:
                updates.append("task_id=?")
                params.append(task_id)
            if error_message is not None:
                updates.append("error_message=?")
                params.append(error_message)
            params.append(record_id)
            conn.execute(
                f"UPDATE import_records SET {', '.join(updates)} WHERE id=?",
                params,
            )
        return ImportRecord.get_by_id(record_id)
