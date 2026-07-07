"""分析结果相关数据模型 — 7 个分析结果表的 CRUD 操作."""

import json
import logging
from typing import Any, Optional

from app.database import get_connection

logger = logging.getLogger(__name__)


class AnalysisResult:
    """分析结果汇总模型."""

    @staticmethod
    def create_or_replace(host_id: int, risk_level: str, risk_score: int,
                          total_findings: int, summary: str,
                          details: dict) -> dict:
        """创建或替换分析结果（重新分析时覆盖旧结果）."""
        with get_connection() as conn:
            # 删除旧结果
            conn.execute("DELETE FROM analysis_results WHERE host_id = ?", (host_id,))
            cursor = conn.execute(
                """
                INSERT INTO analysis_results (host_id, risk_level, risk_score, total_findings, summary, details)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (host_id, risk_level, risk_score, total_findings, summary,
                 json.dumps(details, ensure_ascii=False)),
            )
            result_id = cursor.lastrowid
        # Transaction committed after with block exits; query on a fresh connection
        return AnalysisResult.get_by_host(host_id)

    @staticmethod
    def get_by_host(host_id: int) -> Optional[dict]:
        """获取主机的分析结果."""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM analysis_results WHERE host_id = ? ORDER BY analyzed_at DESC LIMIT 1",
                (host_id,),
            ).fetchone()
            if row:
                result = dict(row)
                if result.get("details"):
                    try:
                        result["details"] = json.loads(result["details"])
                    except (json.JSONDecodeError, TypeError):
                        pass
                return result
            return None


class HostProfile:
    """主机画像模型."""

    @staticmethod
    def create_or_replace(host_id: int, cpu_info: str, memory_info: str,
                          disk_info: str, network_info: str,
                          installed_software: str, user_accounts: str,
                          security_products: str, system_summary: str) -> dict:
        """创建或替换主机画像."""
        with get_connection() as conn:
            conn.execute("DELETE FROM host_profiles WHERE host_id = ?", (host_id,))
            cursor = conn.execute(
                """
                INSERT INTO host_profiles
                (host_id, cpu_info, memory_info, disk_info, network_info,
                 installed_software, user_accounts, security_products, system_summary)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (host_id, cpu_info, memory_info, disk_info, network_info,
                 installed_software, user_accounts, security_products, system_summary),
            )
            profile_id = cursor.lastrowid
        # Transaction committed after with block exits; query on a fresh connection
        return HostProfile.get_by_host(host_id)

    @staticmethod
    def get_by_host(host_id: int) -> Optional[dict]:
        """获取主机画像."""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM host_profiles WHERE host_id = ?", (host_id,)
            ).fetchone()
            return dict(row) if row else None


class AbnormalProcess:
    """异常进程模型."""

    @staticmethod
    def batch_create(host_id: int, items: list) -> int:
        """批量创建异常进程记录."""
        if not items:
            return 0
        with get_connection() as conn:
            # 先清除旧记录
            conn.execute("DELETE FROM abnormal_processes WHERE host_id = ?", (host_id,))
            count = 0
            for item in items:
                conn.execute(
                    """
                    INSERT INTO abnormal_processes
                    (host_id, pid, process_name, process_path, command_line,
                     parent_pid, parent_name, reason, rule_name, severity, details)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        host_id,
                        item.get("pid"),
                        item.get("process_name"),
                        item.get("process_path"),
                        item.get("command_line"),
                        item.get("parent_pid"),
                        item.get("parent_name"),
                        item.get("reason"),
                        item.get("rule_name"),
                        item.get("severity", "medium"),
                        json.dumps(item.get("details", {}), ensure_ascii=False) if item.get("details") else None,
                    ),
                )
                count += 1
            return count

    @staticmethod
    def list_by_host(host_id: int) -> list:
        """获取主机的异常进程列表."""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM abnormal_processes WHERE host_id = ?", (host_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def delete_by_host(host_id: int) -> None:
        """删除主机的所有异常进程记录."""
        with get_connection() as conn:
            conn.execute("DELETE FROM abnormal_processes WHERE host_id = ?", (host_id,))


class SuspiciousConnection:
    """可疑外连模型."""

    @staticmethod
    def batch_create(host_id: int, items: list) -> int:
        """批量创建可疑外连记录."""
        if not items:
            return 0
        with get_connection() as conn:
            conn.execute("DELETE FROM suspicious_connections WHERE host_id = ?", (host_id,))
            count = 0
            for item in items:
                conn.execute(
                    """
                    INSERT INTO suspicious_connections
                    (host_id, protocol, local_address, local_port, remote_address,
                     remote_port, state, process_name, pid, reason, rule_name, severity)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        host_id,
                        item.get("protocol"),
                        item.get("local_address"),
                        item.get("local_port"),
                        item.get("remote_address"),
                        item.get("remote_port"),
                        item.get("state"),
                        item.get("process_name"),
                        item.get("pid"),
                        item.get("reason"),
                        item.get("rule_name"),
                        item.get("severity", "medium"),
                    ),
                )
                count += 1
            return count

    @staticmethod
    def list_by_host(host_id: int) -> list:
        """获取主机的可疑外连列表."""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM suspicious_connections WHERE host_id = ?", (host_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def delete_by_host(host_id: int) -> None:
        """删除主机的所有可疑外连记录."""
        with get_connection() as conn:
            conn.execute("DELETE FROM suspicious_connections WHERE host_id = ?", (host_id,))


class SuspiciousStartupItem:
    """可疑启动项模型."""

    @staticmethod
    def batch_create(host_id: int, items: list) -> int:
        """批量创建可疑启动项记录."""
        if not items:
            return 0
        with get_connection() as conn:
            conn.execute("DELETE FROM suspicious_startup_items WHERE host_id = ?", (host_id,))
            count = 0
            for item in items:
                conn.execute(
                    """
                    INSERT INTO suspicious_startup_items
                    (host_id, name, command, location, type, user, reason, rule_name, severity)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        host_id,
                        item.get("name"),
                        item.get("command"),
                        item.get("location"),
                        item.get("type"),
                        item.get("user"),
                        item.get("reason"),
                        item.get("rule_name"),
                        item.get("severity", "medium"),
                    ),
                )
                count += 1
            return count

    @staticmethod
    def list_by_host(host_id: int) -> list:
        """获取主机的可疑启动项列表."""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM suspicious_startup_items WHERE host_id = ?", (host_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def delete_by_host(host_id: int) -> None:
        """删除主机的所有可疑启动项记录."""
        with get_connection() as conn:
            conn.execute("DELETE FROM suspicious_startup_items WHERE host_id = ?", (host_id,))


class PersistenceItem:
    """持久化痕迹模型."""

    @staticmethod
    def batch_create(host_id: int, items: list) -> int:
        """批量创建持久化痕迹记录."""
        if not items:
            return 0
        with get_connection() as conn:
            conn.execute("DELETE FROM persistence_items WHERE host_id = ?", (host_id,))
            count = 0
            for item in items:
                conn.execute(
                    """
                    INSERT INTO persistence_items
                    (host_id, type, name, command, location, user, is_suspicious, reason, details)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        host_id,
                        item.get("type"),
                        item.get("name"),
                        item.get("command"),
                        item.get("location"),
                        item.get("user"),
                        1 if item.get("is_suspicious") else 0,
                        item.get("reason"),
                        json.dumps(item.get("details", {}), ensure_ascii=False) if item.get("details") else None,
                    ),
                )
                count += 1
            return count

    @staticmethod
    def list_by_host(host_id: int) -> list:
        """获取主机的持久化痕迹列表."""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM persistence_items WHERE host_id = ? ORDER BY is_suspicious DESC, type",
                (host_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def delete_by_host(host_id: int) -> None:
        """删除主机的所有持久化痕迹记录."""
        with get_connection() as conn:
            conn.execute("DELETE FROM persistence_items WHERE host_id = ?", (host_id,))


class TimelineEvent:
    """时间线事件模型."""

    @staticmethod
    def batch_create(host_id: int, items: list) -> int:
        """批量创建时间线事件记录."""
        if not items:
            return 0
        with get_connection() as conn:
            conn.execute("DELETE FROM timeline_events WHERE host_id = ?", (host_id,))
            count = 0
            for item in items:
                conn.execute(
                    """
                    INSERT INTO timeline_events
                    (host_id, timestamp, event_type, source, description, severity, details)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        host_id,
                        item.get("timestamp"),
                        item.get("event_type", "other"),
                        item.get("source"),
                        item.get("description"),
                        item.get("severity", "info"),
                        json.dumps(item.get("details", {}), ensure_ascii=False) if item.get("details") else None,
                    ),
                )
                count += 1
            return count

    @staticmethod
    def list_by_host(host_id: int, start: Optional[str] = None,
                     end: Optional[str] = None, event_type: Optional[str] = None) -> list:
        """获取主机的时间线事件列表（支持时间范围和类型过滤）."""
        with get_connection() as conn:
            query = "SELECT * FROM timeline_events WHERE host_id = ?"
            params: list = [host_id]
            if start:
                query += " AND timestamp >= ?"
                params.append(start)
            if end:
                query += " AND timestamp <= ?"
                params.append(end)
            if event_type:
                query += " AND event_type = ?"
                params.append(event_type)
            query += " ORDER BY timestamp ASC"
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def delete_by_host(host_id: int) -> None:
        """删除主机的所有时间线事件记录."""
        with get_connection() as conn:
            conn.execute("DELETE FROM timeline_events WHERE host_id = ?", (host_id,))


class IocHit:
    """IOC 命中模型."""

    @staticmethod
    def batch_create(host_id: int, items: list) -> int:
        """批量创建 IOC 命中记录."""
        if not items:
            return 0
        with get_connection() as conn:
            conn.execute("DELETE FROM ioc_hits WHERE host_id = ?", (host_id,))
            count = 0
            for item in items:
                conn.execute(
                    """
                    INSERT INTO ioc_hits
                    (host_id, ioc_type, ioc_value, matched_in, context, severity)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        host_id,
                        item.get("ioc_type"),
                        item.get("ioc_value"),
                        item.get("matched_in"),
                        item.get("context"),
                        item.get("severity", "medium"),
                    ),
                )
                count += 1
            return count

    @staticmethod
    def list_by_host(host_id: int) -> list:
        """获取主机的 IOC 命中列表."""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM ioc_hits WHERE host_id = ?", (host_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def delete_by_host(host_id: int) -> None:
        """删除主机的所有 IOC 命中记录."""
        with get_connection() as conn:
            conn.execute("DELETE FROM ioc_hits WHERE host_id = ?", (host_id,))


def clear_analysis_by_host(host_id: int) -> None:
    """清除主机的所有分析结果（重新分析前调用）."""
    with get_connection() as conn:
        conn.execute("DELETE FROM analysis_results WHERE host_id = ?", (host_id,))
        conn.execute("DELETE FROM host_profiles WHERE host_id = ?", (host_id,))
        conn.execute("DELETE FROM abnormal_processes WHERE host_id = ?", (host_id,))
        conn.execute("DELETE FROM suspicious_connections WHERE host_id = ?", (host_id,))
        conn.execute("DELETE FROM suspicious_startup_items WHERE host_id = ?", (host_id,))
        conn.execute("DELETE FROM persistence_items WHERE host_id = ?", (host_id,))
        conn.execute("DELETE FROM timeline_events WHERE host_id = ?", (host_id,))
        conn.execute("DELETE FROM ioc_hits WHERE host_id = ?", (host_id,))
