"""Agent 注册与心跳模型."""
import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional

from app.database import get_connection

logger = logging.getLogger(__name__)


class AgentModel:
    """Agent 注册模型."""

    @staticmethod
    def register(host_id: int, agent_version: str = None, os_type: str = None,
                 collectors: list = None, ip_address: str = None) -> Optional[dict]:
        """注册 Agent，自动生成 agent_id."""
        try:
            agent_id = f"agent-{uuid.uuid4().hex[:12]}"
            collectors_json = ",".join(collectors) if collectors else ""
            with get_connection() as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO agents
                       (host_id, agent_id, agent_version, os_type, collectors, status, last_heartbeat, ip_address)
                       VALUES (?, ?, ?, ?, ?, 'online', datetime('now'), ?)""",
                    [host_id, agent_id, agent_version, os_type, collectors_json, ip_address]
                )
                return {"agent_id": agent_id, "host_id": host_id}
        except Exception as e:
            logger.error("Agent register failed: %s", e)
            return None

    @staticmethod
    def heartbeat(host_id: int) -> bool:
        """更新心跳."""
        try:
            with get_connection() as conn:
                conn.execute(
                    "UPDATE agents SET status='online', last_heartbeat=datetime('now') WHERE host_id=?",
                    [host_id]
                )
                return True
        except Exception as e:
            logger.error("Agent heartbeat failed: %s", e)
            return False

    @staticmethod
    def disconnect(host_id: int) -> bool:
        """标记离线."""
        try:
            with get_connection() as conn:
                conn.execute(
                    "UPDATE agents SET status='offline', last_heartbeat=datetime('now') WHERE host_id=?",
                    [host_id]
                )
                return True
        except Exception as e:
            logger.error("Agent disconnect failed: %s", e)
            return False

    @staticmethod
    def get_online_hosts(timeout_seconds: int = 90) -> list:
        """获取在线主机列表（timeout_seconds 秒内有心跳）. """
        try:
            with get_connection() as conn:
                rows = conn.execute(
                    """SELECT h.id, h.hostname, h.ip_address,
                              a.status, a.last_heartbeat, a.agent_version, a.os_type
                       FROM hosts h LEFT JOIN agents a ON h.id = a.host_id
                       WHERE a.last_heartbeat > datetime('now', ? || ' seconds')
                       ORDER BY a.last_heartbeat DESC""",
                    [f'-{timeout_seconds}']
                ).fetchall()
                return [dict(r) for r in rows]
        except Exception as e:
            logger.error("get_online_hosts failed: %s", e)
            return []

    @staticmethod
    def get_all_with_status(timeout_seconds: int = 90) -> list:
        """获取所有主机的在线/离线状态."""
        try:
            with get_connection() as conn:
                rows = conn.execute(
                    """SELECT h.id, h.hostname, h.ip_address,
                              CASE WHEN a.last_heartbeat > datetime('now', ? || ' seconds')
                                   THEN 'online' ELSE 'offline' END as status,
                              a.last_heartbeat, a.agent_version
                       FROM hosts h LEFT JOIN agents a ON h.id = a.host_id
                       ORDER BY status DESC, h.hostname""",
                    [f'-{timeout_seconds}']
                ).fetchall()
                return [dict(r) for r in rows]
        except Exception as e:
            logger.error("get_all_with_status failed: %s", e)
            return []
