"""规则抑制模型 — 对特定主机的规则设定时效性抑制."""

import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from app.database import get_connection

logger = logging.getLogger(__name__)


class RuleSuppression:
    """规则抑制管理."""

    @staticmethod
    def suppress(rule_name: str, host_id: int, duration_days: int = 7, reason: str = "") -> bool:
        """抑制规则（在指定主机上 N 天内不触发）.

        Args:
            rule_name: 规则名.
            host_id: 主机 ID（0 表示全局抑制）.
            duration_days: 抑制天数.
            reason: 抑制原因.

        Returns:
            是否成功.
        """
        suppressed_until = (datetime.now() + timedelta(days=duration_days)).isoformat()
        try:
            with get_connection() as db:
                # upsert
                existing = db.execute(
                    "SELECT id FROM rule_suppression WHERE rule_name=? AND host_id=?",
                    [rule_name, host_id]
                ).fetchone()
                if existing:
                    db.execute(
                        "UPDATE rule_suppression SET suppressed_until=?, reason=? WHERE id=?",
                        [suppressed_until, reason, existing[0]]
                    )
                else:
                    db.execute(
                        "INSERT INTO rule_suppression (rule_name, host_id, suppressed_until, reason) VALUES (?, ?, ?, ?)",
                        [rule_name, host_id, suppressed_until, reason]
                    )
            logger.info("Suppressed rule '%s' on host %d until %s (%s)", rule_name, host_id, suppressed_until, reason)
            return True
        except Exception as e:
            logger.error("Failed to suppress rule '%s': %s", rule_name, e)
            return False

    @staticmethod
    def is_suppressed(rule_name: str, host_id: int) -> bool:
        """检查规则是否被抑制."""
        try:
            with get_connection() as db:
                row = db.execute(
                    "SELECT suppressed_until FROM rule_suppression WHERE rule_name=? AND (host_id=? OR host_id=0) ORDER BY host_id DESC LIMIT 1",
                    [rule_name, host_id]
                ).fetchone()
                if row:
                    until = row[0]
                    if until and until > datetime.now().isoformat():
                        return True
                return False
        except Exception:
            return False

    @staticmethod
    def list_suppressed(host_id: int = None) -> list[dict]:
        """列出所有抑制记录."""
        try:
            with get_connection() as conn:
                if host_id:
                    rows = conn.execute(
                        "SELECT * FROM rule_suppression WHERE host_id=? OR host_id=0 ORDER BY created_at DESC",
                        [host_id]
                    ).fetchall()
                else:
                    rows = conn.execute("SELECT * FROM rule_suppression ORDER BY created_at DESC").fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error("Failed to list suppressions: %s", e)
            return []

    @staticmethod
    def remove(rule_name: str, host_id: int) -> bool:
        """移除抑制."""
        try:
            with get_connection() as db:
                db.execute("DELETE FROM rule_suppression WHERE rule_name=? AND host_id=?", [rule_name, host_id])
            return True
        except Exception as e:
            logger.error("Failed to remove suppression: %s", e)
            return False
