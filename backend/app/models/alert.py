"""实时告警模型（Alert）."""
import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from app.database import get_connection

logger = logging.getLogger(__name__)


class Alert:
    """实时告警模型."""

    @staticmethod
    def create(host_id: int, rule_name: str, severity: str, title: str,
               detail: str = None, source_pid: int = None,
               source_process: str = None, source_path: str = None,
               source_ip: str = None, case_id: int = None,
               rule_label: str = None) -> Optional[dict]:
        """创建新告警."""
        try:
            with get_connection() as conn:
                cur = conn.execute(
                    """INSERT INTO alerts
                       (host_id, case_id, rule_name, rule_label, severity, title,
                        detail, source_pid, source_process, source_path, source_ip,
                        count, first_seen_at, last_seen_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, datetime('now'), datetime('now'))""",
                    [host_id, case_id, rule_name, rule_label, severity, title,
                     json.dumps(detail, ensure_ascii=False) if isinstance(detail, dict) else detail,
                     source_pid, source_process, source_path, source_ip]
                )
                alert_id = cur.lastrowid
            # 在 with 块外调用 get_by_id（确保数据已提交）
            return Alert.get_by_id(alert_id)
        except Exception as e:
            logger.error("Failed to create alert: %s", e)
            return None

    @staticmethod
    def create_or_aggregate(host_id: int, rule_name: str, severity: str, title: str,
                            detail: str = None, **kwargs) -> tuple:
        """创建或聚合告警（5分钟内相同规则→count+1）.

        Returns:
            (alert_id, is_new): is_new=True为新告警.
        """
        try:
            with get_connection() as conn:
                recent = conn.execute(
                    """SELECT id, count FROM alerts
                       WHERE host_id=? AND rule_name=? AND status='open'
                       AND last_seen_at > datetime('now', '-5 minutes')""",
                    [host_id, rule_name]
                ).fetchone()
                if recent:
                    conn.execute(
                        "UPDATE alerts SET count=count+1, last_seen_at=datetime('now') WHERE id=?",
                        [recent[0]]
                    )
                    return recent[0], False
                alert = Alert.create(host_id, rule_name, severity, title, detail, **kwargs)
                return (alert["id"], True) if alert else (None, False)
        except Exception as e:
            logger.error("Alert create_or_aggregate failed: %s", e)
            return (None, False)

    @staticmethod
    def list(host_id: int = None, severity: str = None, status: str = None,
             rule_name: str = None, case_id: int = None,
             date_from: str = None, date_to: str = None, search: str = None,
             limit: int = 100, offset: int = 0) -> list:
        """列出告警（支持多条件筛选）. """
        try:
            conditions = ["1=1"]
            params = []
            if host_id is not None:
                conditions.append("host_id=?")
                params.append(host_id)
            if severity:
                conditions.append("severity=?")
                params.append(severity)
            if status:
                conditions.append("status=?")
                params.append(status)
            if rule_name:
                conditions.append("rule_name=?")
                params.append(rule_name)
            if case_id is not None:
                conditions.append("host_id IN (SELECT id FROM hosts WHERE case_id=?)")
                params.append(case_id)
            if date_from:
                conditions.append("first_seen_at >= ?")
                params.append(date_from)
            if date_to:
                conditions.append("first_seen_at <= ?")
                params.append(date_to)
            if search:
                conditions.append("(title LIKE ? OR detail LIKE ? OR source_process LIKE ? OR rule_name LIKE ?)")
                params.extend([f"%{search}%"] * 4)
            sql = f"SELECT * FROM alerts WHERE {' AND '.join(conditions)} ORDER BY last_seen_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            with get_connection() as conn:
                return [dict(r) for r in conn.execute(sql, params).fetchall()]
        except Exception as e:
            logger.error("Alert list failed: %s", e)
            return []

    @staticmethod
    def get_by_id(alert_id: int) -> Optional[dict]:
        try:
            with get_connection() as conn:
                row = conn.execute("SELECT * FROM alerts WHERE id=?", [alert_id]).fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error("Alert get_by_id failed: %s", e)
            return None

    @staticmethod
    def acknowledge(alert_id: int, user: str = "system") -> bool:
        try:
            with get_connection() as conn:
                conn.execute(
                    "UPDATE alerts SET status='acknowledged', acknowledged_by=?, acknowledged_at=datetime('now') WHERE id=?",
                    [user, alert_id]
                )
                return True
        except Exception as e:
            logger.error("Alert acknowledge failed: %s", e)
            return False

    @staticmethod
    def resolve(alert_id: int) -> bool:
        try:
            with get_connection() as conn:
                conn.execute(
                    "UPDATE alerts SET status='resolved', resolved_at=datetime('now') WHERE id=?",
                    [alert_id]
                )
                return True
        except Exception as e:
            logger.error("Alert resolve failed: %s", e)
            return False

    @staticmethod
    def dismiss(alert_id: int, reason: str = "") -> bool:
        try:
            with get_connection() as conn:
                conn.execute(
                    "UPDATE alerts SET status='dismissed', dismissed_reason=? WHERE id=?",
                    [reason, alert_id]
                )
                return True
        except Exception as e:
            logger.error("Alert dismiss failed: %s", e)
            return False

    @staticmethod
    def get_stats(host_id: int = None, severity: str = None, status: str = None,
                  rule_name: str = None, case_id: int = None,
                  date_from: str = None, date_to: str = None,
                  search: str = None) -> dict:
        """获取告警统计数据（支持筛选范围）. """
        try:
            conditions = ["1=1"]
            params = []
            if host_id is not None:
                conditions.append("host_id=?")
                params.append(host_id)
            if severity:
                conditions.append("severity=?")
                params.append(severity)
            if status:
                conditions.append("status=?")
                params.append(status)
            if rule_name:
                conditions.append("rule_name=?")
                params.append(rule_name)
            if case_id is not None:
                conditions.append("host_id IN (SELECT id FROM hosts WHERE case_id=?)")
                params.append(case_id)
            if date_from:
                conditions.append("first_seen_at >= ?")
                params.append(date_from)
            if date_to:
                conditions.append("first_seen_at <= ?")
                params.append(date_to)
            if search:
                conditions.append("(title LIKE ? OR detail LIKE ? OR source_process LIKE ? OR rule_name LIKE ?)")
                params.extend([f"%{search}%"] * 4)
            where_clause = " AND ".join(conditions)
            with get_connection() as conn:
                total = conn.execute(f"SELECT COUNT(*) FROM alerts WHERE {where_clause}", params).fetchone()[0]
                open_count = conn.execute(f"SELECT COUNT(*) FROM alerts WHERE status='open' AND {where_clause}", params).fetchone()[0]
                critical = conn.execute(f"SELECT COUNT(*) FROM alerts WHERE severity='critical' AND status='open' AND {where_clause}", params).fetchone()[0]
                # 全量严重度分布（不受status过滤）
                sev_rows = conn.execute(
                    f"SELECT severity, COUNT(*) FROM alerts WHERE {where_clause} GROUP BY severity",
                    params
                ).fetchall()
                severity_dist = {row[0]: row[1] for row in sev_rows}
                today_start = datetime.now().strftime("%Y-%m-%d 00:00:00")
                today = conn.execute(f"SELECT COUNT(*) FROM alerts WHERE first_seen_at >= ? AND {where_clause}",
                                     [today_start] + params).fetchone()[0]
                # 近1小时新增
                hour_ago = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
                hourly = conn.execute(
                    f"SELECT COUNT(*) FROM alerts WHERE first_seen_at >= ? AND {where_clause}",
                    [hour_ago] + params
                ).fetchone()[0]
                # 7 天内规则命中统计
                week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
                rule_hits = conn.execute(
                    f"SELECT COALESCE(SUM(count), 0) FROM alerts WHERE first_seen_at >= ? AND {where_clause}",
                    [week_ago] + params
                ).fetchone()[0]
                active_rules = conn.execute(
                    f"SELECT COUNT(DISTINCT rule_name) FROM alerts WHERE first_seen_at >= ? AND {where_clause}",
                    [week_ago] + params
                ).fetchone()[0]
                return {
                    "total": total,
                    "open": open_count,
                    "critical": critical,
                    "today": today,
                    "hourly": hourly,
                    "severity_dist": severity_dist,
                    "rule_hits": rule_hits,
                    "active_rules": active_rules,
                }
        except Exception:
            return {"total": 0, "open": 0, "critical": 0, "today": 0}

    @staticmethod
    def get_trend(hours: int = 24) -> list:
        """获取告警趋势（按小时聚合）. """
        try:
            with get_connection() as conn:
                rows = conn.execute(
                    """SELECT strftime('%Y-%m-%d %H:00', first_seen_at) as hour,
                              COUNT(*) as cnt, severity
                       FROM alerts WHERE first_seen_at >= datetime('now', ? || ' hours')
                       GROUP BY hour, severity ORDER BY hour""",
                    [f'-{hours}']
                ).fetchall()
                trend = {}
                for r in rows:
                    h = r["hour"]
                    if h not in trend:
                        trend[h] = {"hour": h, "critical": 0, "high": 0, "medium": 0, "total": 0}
                    trend[h][r["severity"]] = trend[h].get(r["severity"], 0) + r["cnt"]
                    trend[h]["total"] += r["cnt"]
                return sorted(trend.values(), key=lambda x: x["hour"])
        except Exception:
            return []
