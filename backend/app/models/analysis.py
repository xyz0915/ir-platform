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
        """批量创建异常进程记录（含 risk_score/matched_rules/attack_path 新增字段）."""
        if not items:
            return 0
        with get_connection() as conn:
            # 先清除旧记录
            conn.execute("DELETE FROM abnormal_processes WHERE host_id = ?", (host_id,))
            count = 0
            for item in items:
                # matched_rules 序列化为 JSON 字符串
                matched_rules_data = item.get("matched_rules")
                if matched_rules_data is not None:
                    matched_rules_str = json.dumps(matched_rules_data, ensure_ascii=False)
                else:
                    matched_rules_str = None

                conn.execute(
                    """
                    INSERT INTO abnormal_processes
                    (host_id, pid, process_name, process_path, command_line,
                     parent_pid, parent_name, reason, rule_name, severity, details,
                     risk_score, matched_rules, attack_path)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        item.get("risk_score", 0),
                        matched_rules_str,
                        item.get("attack_path"),
                    ),
                )
                count += 1
            return count

    @staticmethod
    def list_by_host(host_id: int) -> list:
        """获取主机的异常进程列表（含 risk_score/matched_rules/attack_path 字段解析）."""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM abnormal_processes WHERE host_id = ?", (host_id,)
            ).fetchall()
            result_list = []
            for r in rows:
                proc = dict(r)
                # 对 matched_rules 做 JSON 解析（如果非 null）
                if proc.get("matched_rules") and isinstance(proc.get("matched_rules"), str):
                    try:
                        proc["matched_rules"] = json.loads(proc["matched_rules"])
                    except (json.JSONDecodeError, TypeError):
                        # 解析失败时保留原字符串
                        pass
                elif proc.get("matched_rules") is None:
                    proc["matched_rules"] = []
                result_list.append(proc)
            return result_list

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
    def update_threat_info(rows: list) -> int:
        """批量回写威胁情报字段（按 id 匹配）.

        用于「一键威胁情报检测」将 enrichment 结果写回可疑外连行。

        Args:
            rows: 列表，每项字典含字段:
                id            — 可疑外连行主键
                threat_level  — 派生威胁等级 high/medium/low/None
                threat_score  — 风险评分 0-100
                threat_tags   — JSON 字符串（标签数组）
                enriched_at   — 检测时间（TEXT）

        Returns:
            成功更新的行数。
        """
        if not rows:
            return 0
        with get_connection() as conn:
            count = 0
            for row in rows:
                conn.execute(
                    """
                    UPDATE suspicious_connections
                    SET threat_level = ?, threat_score = ?, threat_tags = ?, enriched_at = ?
                    WHERE id = ?
                    """,
                    (
                        row.get("threat_level"),
                        int(row.get("threat_score") or 0),
                        row.get("threat_tags"),
                        row.get("enriched_at"),
                        row.get("id"),
                    ),
                )
                count += 1
            return count

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
        """批量创建时间线事件记录（含 V1-5 新增字段）."""
        if not items:
            return 0
        with get_connection() as conn:
            conn.execute("DELETE FROM timeline_events WHERE host_id = ?", (host_id,))
            count = 0
            for item in items:
                conn.execute(
                    """
                    INSERT INTO timeline_events
                    (host_id, timestamp, event_type, source, description, severity, details,
                     kill_chain_stage, mitre_technique_id, status, assigned_to, resolution, ioc_hit_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        host_id,
                        item.get("timestamp"),
                        item.get("event_type", "other"),
                        item.get("source"),
                        item.get("description"),
                        item.get("severity", "info"),
                        json.dumps(item.get("details", {}), ensure_ascii=False) if item.get("details") else None,
                        item.get("kill_chain_stage"),
                        item.get("mitre_technique_id"),
                        item.get("status", "new"),
                        item.get("assigned_to"),
                        item.get("resolution"),
                        item.get("ioc_hit_id"),
                    ),
                )
                count += 1
            return count

    @staticmethod
    def list_by_host(host_id: int, start: Optional[str] = None,
                     end: Optional[str] = None, event_type: Optional[str] = None,
                     severities: Optional[str] = None, event_types: Optional[str] = None,
                     ioc_hit: Optional[bool] = None) -> list:
        """获取主机的时间线事件列表（支持时间范围和类型/严重度/IOC过滤）.

        Args:
            host_id: 主机 ID.
            start: 开始时间（ISO 8601）.
            end: 结束时间（ISO 8601）.
            event_type: 单个事件类型（向后兼容）.
            severities: 逗号分隔的严重度列表，如 "high,medium".
            event_types: 逗号分隔的事件类型列表，如 "process,network".
            ioc_hit: 为 True 时仅返回 ioc_hit_id 非空的事件.

        Returns:
            事件列表.
        """
        with get_connection() as conn:
            query = "SELECT * FROM timeline_events WHERE host_id = ?"
            params: list = [host_id]
            if start:
                query += " AND timestamp >= ?"
                params.append(start)
            if end:
                query += " AND timestamp <= ?"
                params.append(end)
            # 优先级：新参数 event_types（逗号分隔）> 旧参数 event_type（单值）
            if event_types:
                types_list = [t.strip() for t in event_types.split(",") if t.strip()]
                if types_list:
                    placeholders = ",".join(["?"] * len(types_list))
                    query += f" AND event_type IN ({placeholders})"
                    params.extend(types_list)
            elif event_type:
                query += " AND event_type = ?"
                params.append(event_type)
            if severities:
                sev_list = [s.strip() for s in severities.split(",") if s.strip()]
                if sev_list:
                    placeholders = ",".join(["?"] * len(sev_list))
                    query += f" AND severity IN ({placeholders})"
                    params.extend(sev_list)
            if ioc_hit:
                query += " AND ioc_hit_id IS NOT NULL"
            query += " ORDER BY timestamp ASC"
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def get_stats(host_id: int) -> dict:
        """获取主机时间线事件统计摘要.

        一次 SQL 聚合查询返回:
          - highCount: 高危事件数
          - mediumCount: 中危事件数
          - lowCount: 低危事件数
          - iocHitCount: IOC 命中事件数
          - timeSpan: 时间跨度（小时），若无事件则返回 0

        Args:
            host_id: 主机 ID.

        Returns:
            统计字典.
        """
        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT
                    COALESCE(SUM(CASE WHEN severity = 'high' THEN 1 ELSE 0 END), 0) AS highCount,
                    COALESCE(SUM(CASE WHEN severity = 'medium' THEN 1 ELSE 0 END), 0) AS mediumCount,
                    COALESCE(SUM(CASE WHEN severity = 'low' THEN 1 ELSE 0 END), 0) AS lowCount,
                    COALESCE(SUM(CASE WHEN ioc_hit_id IS NOT NULL THEN 1 ELSE 0 END), 0) AS iocHitCount,
                    COALESCE(
                        ROUND(
                            (JULIANDAY(MAX(timestamp)) - JULIANDAY(MIN(timestamp))) * 24,
                            1
                        ),
                        0
                    ) AS timeSpan
                FROM timeline_events
                WHERE host_id = ?
                """,
                (host_id,),
            ).fetchone()
            if row:
                return {
                    "highCount": row["highCount"],
                    "mediumCount": row["mediumCount"],
                    "lowCount": row["lowCount"],
                    "iocHitCount": row["iocHitCount"],
                    "timeSpan": row["timeSpan"],
                }
            return {"highCount": 0, "mediumCount": 0, "lowCount": 0, "iocHitCount": 0, "timeSpan": 0}

    @staticmethod
    def update_status(event_id: int, data: dict) -> dict:
        """更新事件处置状态并写入审计日志.

        Args:
            event_id: 事件 ID.
            data: 包含 status/resolution/operator 的字典.

        Returns:
            更新后的事件字典.
        """
        with get_connection() as conn:
            # 读取旧状态
            old_row = conn.execute(
                "SELECT status FROM timeline_events WHERE id = ?", (event_id,)
            ).fetchone()
            if not old_row:
                raise ValueError(f"事件 {event_id} 不存在")

            old_status = old_row["status"]
            new_status = data.get("status", old_status)
            resolution = data.get("resolution")
            operator = data.get("operator")
            assigned_to = data.get("assigned_to")

            # 更新事件
            conn.execute(
                """
                UPDATE timeline_events
                SET status = ?, resolution = ?, assigned_to = ?, updated_at = datetime('now')
                WHERE id = ?
                """,
                (new_status, resolution, assigned_to, event_id),
            )

            # 写入审计日志
            conn.execute(
                """
                INSERT INTO timeline_event_audit
                (event_id, old_status, new_status, operator, comment)
                VALUES (?, ?, ?, ?, ?)
                """,
                (event_id, old_status, new_status, operator, resolution),
            )

        # 返回更新后的事件
        return TimelineEvent.get_by_id(event_id)

    @staticmethod
    def get_by_id(event_id: int) -> Optional[dict]:
        """根据 ID 获取单个时间线事件."""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM timeline_events WHERE id = ?", (event_id,)
            ).fetchone()
            if row:
                result = dict(row)
                if result.get("details") and isinstance(result["details"], str):
                    try:
                        result["details"] = json.loads(result["details"])
                    except (json.JSONDecodeError, TypeError):
                        pass
                return result
            return None

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
    def append(host_id: int, items: list) -> int:
        """追加 IOC 命中记录（不删除既有记录，供增量写入通道复用）.

        与 batch_create 的区别：batch_create 会先 DELETE 本机全部 ioc_hits
        （用于 step 6 常规 IOC 检测的整体刷新）；本方法仅 INSERT，避免覆盖
        同一次分析流程中其他环节已写入的 ioc_hits（如文件哈希情报命中）。

        Args:
            host_id: 主机 ID.
            items: 待追加的命中列表，每项为
                   {ioc_type, ioc_value, matched_in, context, severity}.

        Returns:
            新增记录数.
        """
        if not items:
            return 0
        with get_connection() as conn:
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
        conn.execute("DELETE FROM network_connections WHERE host_id = ?", (host_id,))
        conn.execute("DELETE FROM file_hashes WHERE host_id = ?", (host_id,))
        conn.execute("DELETE FROM wmi_subscriptions WHERE host_id = ?", (host_id,))
        conn.execute("DELETE FROM registry_keys WHERE host_id = ?", (host_id,))


class NetworkConnection:
    """网络连接模型（数据采集增强 P1-2）."""

    @staticmethod
    def batch_create(host_id: int, items: list) -> int:
        """批量创建网络连接记录."""
        if not items:
            return 0
        with get_connection() as conn:
            conn.execute("DELETE FROM network_connections WHERE host_id = ?", (host_id,))
            count = 0
            for item in items:
                conn.execute(
                    """
                    INSERT INTO network_connections
                    (host_id, protocol, local_addr, local_port, remote_addr,
                     remote_port, state, pid, process_name, collected_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        host_id,
                        item.get("protocol"),
                        item.get("local_addr"),
                        item.get("local_port"),
                        item.get("remote_addr"),
                        item.get("remote_port"),
                        item.get("state"),
                        item.get("pid"),
                        item.get("process_name"),
                        item.get("collected_at"),
                    ),
                )
                count += 1
            return count

    @staticmethod
    def list_by_host(host_id: int) -> list:
        """获取主机的网络连接列表."""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM network_connections WHERE host_id = ? ORDER BY id",
                (host_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def delete_by_host(host_id: int) -> None:
        """删除主机的所有网络连接记录."""
        with get_connection() as conn:
            conn.execute("DELETE FROM network_connections WHERE host_id = ?", (host_id,))

    @staticmethod
    def update_threat_info(rows: list) -> int:
        """批量回写威胁情报字段（按 id 匹配）."""
        if not rows:
            return 0
        with get_connection() as conn:
            count = 0
            for row in rows:
                conn.execute(
                    "UPDATE network_connections SET threat_level=?, threat_score=?, threat_tags=?, enriched_at=? WHERE id=?",
                    (row.get("threat_level"), row.get("threat_score"), row.get("threat_tags"), row.get("enriched_at"), row["id"]),
                )
                count += 1
            return count


class FileHash:
    """文件哈希模型（数据采集增强 P1-3）."""

    @staticmethod
    def batch_create(host_id: int, items: list) -> int:
        """批量创建文件哈希记录."""
        if not items:
            return 0
        with get_connection() as conn:
            conn.execute("DELETE FROM file_hashes WHERE host_id = ?", (host_id,))
            count = 0
            for item in items:
                conn.execute(
                    """
                    INSERT INTO file_hashes
                    (host_id, file_path, file_name, sha256, is_signed, signer,
                     file_size, product_name, product_version, collected_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        host_id,
                        item.get("file_path"),
                        item.get("file_name"),
                        item.get("sha256"),
                        1 if item.get("is_signed") else 0,
                        item.get("signer"),
                        item.get("file_size"),
                        item.get("product_name"),
                        item.get("product_version"),
                        item.get("collected_at"),
                    ),
                )
                count += 1
            return count

    @staticmethod
    def list_by_host(host_id: int) -> list:
        """获取主机的文件哈希列表."""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM file_hashes WHERE host_id = ? ORDER BY id",
                (host_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def delete_by_host(host_id: int) -> None:
        """删除主机的所有文件哈希记录."""
        with get_connection() as conn:
            conn.execute("DELETE FROM file_hashes WHERE host_id = ?", (host_id,))


class WmiSubscription:
    """WMI 订阅模型（数据采集增强 P1-5）.

    event_filter / event_consumer 字段存储为 JSON 字符串，
    list_by_host 自动做 json.loads() 反序列化，
    batch_create 自动对 dict 值做 json.dumps() 序列化。
    """

    @staticmethod
    def batch_create(host_id: int, items: list) -> int:
        """批量创建 WMI 订阅记录."""
        if not items:
            return 0
        with get_connection() as conn:
            conn.execute("DELETE FROM wmi_subscriptions WHERE host_id = ?", (host_id,))
            count = 0
            for item in items:
                event_filter = item.get("event_filter")
                event_consumer = item.get("event_consumer")
                # 对 dict 类型做 json.dumps() 序列化
                if isinstance(event_filter, dict):
                    event_filter = json.dumps(event_filter, ensure_ascii=False)
                if isinstance(event_consumer, dict):
                    event_consumer = json.dumps(event_consumer, ensure_ascii=False)
                conn.execute(
                    """
                    INSERT INTO wmi_subscriptions
                    (host_id, name, event_filter, event_consumer,
                     binding_type, risk_level, collected_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        host_id,
                        item.get("name"),
                        event_filter,
                        event_consumer,
                        item.get("binding_type"),
                        item.get("risk_level"),
                        item.get("collected_at"),
                    ),
                )
                count += 1
            return count

    @staticmethod
    def list_by_host(host_id: int) -> list:
        """获取主机的 WMI 订阅列表.

        event_filter 和 event_consumer 字段自动做 json.loads() 反序列化。
        如果字段为 None 或非法 JSON，返回原值。
        """
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM wmi_subscriptions WHERE host_id = ? ORDER BY id",
                (host_id,),
            ).fetchall()
            result_list = []
            for r in rows:
                sub = dict(r)
                # 反序列化 event_filter
                if sub.get("event_filter") is not None and isinstance(sub["event_filter"], str):
                    try:
                        sub["event_filter"] = json.loads(sub["event_filter"])
                    except (json.JSONDecodeError, TypeError):
                        pass
                # 反序列化 event_consumer
                if sub.get("event_consumer") is not None and isinstance(sub["event_consumer"], str):
                    try:
                        sub["event_consumer"] = json.loads(sub["event_consumer"])
                    except (json.JSONDecodeError, TypeError):
                        pass
                result_list.append(sub)
            return result_list

    @staticmethod
    def delete_by_host(host_id: int) -> None:
        """删除主机的所有 WMI 订阅记录."""
        with get_connection() as conn:
            conn.execute("DELETE FROM wmi_subscriptions WHERE host_id = ?", (host_id,))


class RegistryKey:
    """注册表键值模型（数据采集增强 P1-6）."""

    @staticmethod
    def batch_create(host_id: int, items: list) -> int:
        """批量创建注册表键值记录."""
        if not items:
            return 0
        with get_connection() as conn:
            conn.execute("DELETE FROM registry_keys WHERE host_id = ?", (host_id,))
            count = 0
            for item in items:
                conn.execute(
                    """
                    INSERT INTO registry_keys
                    (host_id, key_path, value_name, value_type, value_data,
                     last_write_time, collected_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        host_id,
                        item.get("key_path"),
                        item.get("value_name"),
                        item.get("value_type"),
                        item.get("value_data"),
                        item.get("last_write_time"),
                        item.get("collected_at"),
                    ),
                )
                count += 1
            return count

    @staticmethod
    def list_by_host(host_id: int) -> list:
        """获取主机的注册表键值列表."""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM registry_keys WHERE host_id = ? ORDER BY id",
                (host_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def delete_by_host(host_id: int) -> None:
        """删除主机的所有注册表键值记录."""
        with get_connection() as conn:
            conn.execute("DELETE FROM registry_keys WHERE host_id = ?", (host_id,))


class WebShell:
    """WebShell 文件型检测命中模型（融合扩充 A §2.2）.

    落库 detect_webshells 的聚合结果（与 abnormal_processes 同风格）。
    """

    @staticmethod
    def batch_create(host_id: int, items: list) -> int:
        """批量创建 WebShell 命中记录.

        Args:
            host_id: 主机 ID.
            items: detect_webshells 聚合后的命中列表（dict）.

        Returns:
            插入的记录数.
        """
        if not items:
            return 0
        with get_connection() as conn:
            conn.execute("DELETE FROM webshells WHERE host_id = ?", (host_id,))
            count = 0
            for item in items:
                if not isinstance(item, dict):
                    continue
                try:
                    matched_rules = json.dumps(
                        item.get("matched_rules", []), ensure_ascii=False
                    )
                except (TypeError, ValueError):
                    matched_rules = "[]"
                try:
                    suspicious_funcs = json.dumps(
                        item.get("suspicious_funcs", []), ensure_ascii=False
                    )
                except (TypeError, ValueError):
                    suspicious_funcs = "[]"
                try:
                    details = json.dumps(item, ensure_ascii=False)
                except (TypeError, ValueError):
                    details = "{}"
                conn.execute(
                    """
                    INSERT INTO webshells
                    (host_id, path, name, sha256, severity, risk_score,
                     matched_rules, suspicious_funcs, obfuscation_score,
                     behinder_godzilla_signal, details)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        host_id,
                        item.get("path"),
                        item.get("name"),
                        item.get("sha256"),
                        item.get("severity"),
                        int(item.get("risk_score", 0) or 0),
                        matched_rules,
                        suspicious_funcs,
                        item.get("obfuscation_score"),
                        1 if item.get("behinder_godzilla_signal") else 0,
                        details,
                    ),
                )
                count += 1
            return count

    @staticmethod
    def list_by_host(host_id: int) -> list:
        """获取主机的 WebShell 命中列表.

        matched_rules / suspicious_funcs / details 字段自动 json.loads() 反序列化，
        便于前端直接消费（与 AbnormalProcess.list_by_host 风格一致）。
        """
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM webshells WHERE host_id = ? ORDER BY id",
                (host_id,),
            ).fetchall()
            result_list = []
            for r in rows:
                item = dict(r)
                for field in ("matched_rules", "suspicious_funcs", "details"):
                    val = item.get(field)
                    if isinstance(val, str):
                        try:
                            item[field] = json.loads(val)
                        except (json.JSONDecodeError, TypeError):
                            pass
                # 兜底：matched_rules / suspicious_funcs 为 None 时给空数组
                if item.get("matched_rules") is None:
                    item["matched_rules"] = []
                if item.get("suspicious_funcs") is None:
                    item["suspicious_funcs"] = []
                result_list.append(item)
            return result_list

    @staticmethod
    def delete_by_host(host_id: int) -> None:
        """删除主机的所有 WebShell 命中记录."""
        with get_connection() as conn:
            conn.execute("DELETE FROM webshells WHERE host_id = ?", (host_id,))


class MemoryShell:
    """内存码（Java 内存马 / PHP 扩展）检测命中模型（融合扩充 A §2.2）.

    落库 detect_memory_shells 的聚合结果（与 abnormal_processes 同风格）。
    """

    @staticmethod
    def batch_create(host_id: int, items: list) -> int:
        """批量创建内存码命中记录.

        Args:
            host_id: 主机 ID.
            items: detect_memory_shells 聚合后的命中列表（dict）.

        Returns:
            插入的记录数.
        """
        if not items:
            return 0
        with get_connection() as conn:
            conn.execute("DELETE FROM memory_shells WHERE host_id = ?", (host_id,))
            count = 0
            for item in items:
                if not isinstance(item, dict):
                    continue
                try:
                    matched_rules = json.dumps(
                        item.get("matched_rules", []), ensure_ascii=False
                    )
                except (TypeError, ValueError):
                    matched_rules = "[]"
                try:
                    details = json.dumps(item, ensure_ascii=False)
                except (TypeError, ValueError):
                    details = "{}"
                conn.execute(
                    """
                    INSERT INTO memory_shells
                    (host_id, pid, process_name, type, evidence, severity,
                     risk_score, matched_rules, details)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        host_id,
                        item.get("pid"),
                        item.get("process_name"),
                        item.get("type"),
                        item.get("evidence"),
                        item.get("severity"),
                        int(item.get("risk_score", 0) or 0),
                        matched_rules,
                        details,
                    ),
                )
                count += 1
            return count

    @staticmethod
    def list_by_host(host_id: int) -> list:
        """获取主机的内存码命中列表.

        matched_rules / details 字段自动 json.loads() 反序列化，
        便于前端直接消费（与 AbnormalProcess.list_by_host 风格一致）。
        """
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM memory_shells WHERE host_id = ? ORDER BY id",
                (host_id,),
            ).fetchall()
            result_list = []
            for r in rows:
                item = dict(r)
                for field in ("matched_rules", "details"):
                    val = item.get(field)
                    if isinstance(val, str):
                        try:
                            item[field] = json.loads(val)
                        except (json.JSONDecodeError, TypeError):
                            pass
                if item.get("matched_rules") is None:
                    item["matched_rules"] = []
                result_list.append(item)
            return result_list

    @staticmethod
    def delete_by_host(host_id: int) -> None:
        """删除主机的所有内存码命中记录."""
        with get_connection() as conn:
            conn.execute("DELETE FROM memory_shells WHERE host_id = ?", (host_id,))
