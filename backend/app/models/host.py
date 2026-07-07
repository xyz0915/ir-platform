"""Host 数据模型 — 主机 CRUD 操作."""

import logging
from typing import Any, Optional

from app.database import get_connection

logger = logging.getLogger(__name__)


class Host:
    """主机数据模型."""

    @staticmethod
    def create(case_id: int, hostname: str, ip_address: Optional[str] = None,
               os_type: Optional[str] = None, os_version: Optional[str] = None) -> dict:
        """创建主机记录."""
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO hosts (case_id, hostname, ip_address, os_type, os_version, status)
                VALUES (?, ?, ?, ?, ?, 'pending')
                """,
                (case_id, hostname, ip_address, os_type, os_version),
            )
            host_id = cursor.lastrowid
        # Transaction committed after with block exits; query on a fresh connection
        return Host.get_by_id(host_id)

    @staticmethod
    def get_by_id(host_id: int) -> Optional[dict]:
        """根据 ID 获取主机."""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM hosts WHERE id = ?", (host_id,)
            ).fetchone()
            return dict(row) if row else None

    @staticmethod
    def list_by_case(case_id: int) -> list:
        """获取案件下的所有主机."""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM hosts WHERE case_id = ? ORDER BY created_at DESC",
                (case_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def update_status(host_id: int, status: str,
                      raw_json_path: Optional[str] = None,
                      agent_version: Optional[str] = None,
                      collection_time: Optional[str] = None,
                      os_type: Optional[str] = None,
                      os_version: Optional[str] = None,
                      ip_address: Optional[str] = None,
                      hostname: Optional[str] = None) -> Optional[dict]:
        """更新主机状态和信息."""
        with get_connection() as conn:
            fields = ["status = ?"]
            params: list = [status]
            if raw_json_path is not None:
                fields.append("raw_json_path = ?")
                params.append(raw_json_path)
            if agent_version is not None:
                fields.append("agent_version = ?")
                params.append(agent_version)
            if collection_time is not None:
                fields.append("collection_time = ?")
                params.append(collection_time)
            if os_type is not None:
                fields.append("os_type = ?")
                params.append(os_type)
            if os_version is not None:
                fields.append("os_version = ?")
                params.append(os_version)
            if ip_address is not None:
                fields.append("ip_address = ?")
                params.append(ip_address)
            if hostname is not None:
                fields.append("hostname = ?")
                params.append(hostname)
            fields.append("updated_at = datetime('now')")
            params.append(host_id)
            conn.execute(
                f"UPDATE hosts SET {', '.join(fields)} WHERE id = ?",
                params,
            )
        # Transaction committed after with block exits; query on a fresh connection
        return Host.get_by_id(host_id)

    @staticmethod
    def delete(host_id: int) -> bool:
        """删除主机."""
        with get_connection() as conn:
            conn.execute("DELETE FROM hosts WHERE id = ?", (host_id,))
            return True
