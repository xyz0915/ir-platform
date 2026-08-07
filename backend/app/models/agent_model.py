"""Agent 注册与心跳模型."""
import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Optional

from app.config import settings
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
    def generate_token(host_id: int) -> Optional[dict]:
        """生成/重置 Agent 专属 token，明文仅此一次返回，库中仅存哈希.

        Args:
            host_id: 主机 ID（agents.host_id 唯一绑定 hosts.id）.

        Returns:
            ``{"token", "token_hash", "host_id", "agent_id"}``（token 为明文，仅本次返回）；
            失败返回 None.
        """
        try:
            token = "atk_" + secrets.token_urlsafe(32)
            token_hash = hashlib.sha256(
                f"{token}:{settings.SECRET_KEY}".encode("utf-8")
            ).hexdigest()
            with get_connection() as conn:
                conn.execute(
                    "UPDATE agents SET token_hash=?, token_created_at=datetime('now') WHERE host_id=?",
                    [token_hash, host_id],
                )
                row = conn.execute(
                    "SELECT agent_id, token_created_at FROM agents WHERE host_id=?",
                    [host_id],
                ).fetchone()
            if not row:
                logger.warning("Agent generate_token: host_id=%d has no agents row", host_id)
                return None
            return {
                "token": token,
                "token_hash": token_hash,
                "host_id": host_id,
                "agent_id": row["agent_id"],
                "token_created_at": row["token_created_at"],
            }
        except Exception as e:
            logger.error("Agent generate_token failed: %s", e)
            return None

    @staticmethod
    def get_by_token_hash(token_hash: str) -> Optional[dict]:
        """按 token 哈希查询 agent（认证用）.

        Args:
            token_hash: sha256(f"{token}:{SECRET_KEY}") hex 串.

        Returns:
            ``{"host_id", "agent_id", "token_hash"}`` 或 None.
        """
        try:
            with get_connection() as conn:
                row = conn.execute(
                    "SELECT host_id, agent_id, token_hash FROM agents WHERE token_hash=?",
                    [token_hash],
                ).fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error("Agent get_by_token_hash failed: %s", e)
            return None

    @staticmethod
    def get_token_status(host_id: int) -> dict:
        """查询 agent 行 token 状态（供列表/详情展示，不含明文）.

        Args:
            host_id: 主机 ID.

        Returns:
            ``{"token_set": bool, "token_created_at": str|None}``；agents 行不存在时
            ``{"token_set": False, "token_created_at": None}``.
        """
        try:
            with get_connection() as conn:
                row = conn.execute(
                    "SELECT token_hash, token_created_at FROM agents WHERE host_id=?",
                    [host_id],
                ).fetchone()
            if not row:
                return {"token_set": False, "token_created_at": None}
            return {
                "token_set": bool(row["token_hash"]),
                "token_created_at": row["token_created_at"],
            }
        except Exception as e:
            logger.error("Agent get_token_status failed: %s", e)
            return {"token_set": False, "token_created_at": None}

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
