"""范式化日志模型 (NormalizedLog)."""

import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from app.database import get_connection

logger = logging.getLogger(__name__)


class NormalizedLog:

    @staticmethod
    def batch_create(items: list[dict]) -> int:
        """批量写入范式化日志."""
        if not items:
            return 0
        try:
            with get_connection() as conn:
                now = datetime.now().isoformat()
                data = []
                for item in items:
                    data.append((
                        item.get("host_id"), item.get("hostname", ""),
                        item.get("log_source", ""),
                        item.get("event_id", 0),
                        item.get("event_type", ""),
                        item.get("event_label", ""),
                        item.get("mitre_attack", ""),
                        item.get("severity", "info"),
                        item.get("timestamp", ""),
                        item.get("source_ip", ""),
                        item.get("source_hostname", ""),
                        item.get("target_ip", ""),
                        item.get("target_hostname", ""),
                        item.get("user_name", ""),
                        item.get("user_domain", ""),
                        item.get("logon_session", ""),
                        item.get("process_name", ""),
                        item.get("process_pid"),
                        item.get("parent_process_name", ""),
                        item.get("parent_process_pid"),
                        item.get("command_line", ""),
                        item.get("object_name", ""),
                        item.get("tags", ""),
                        item.get("description", ""),
                        item.get("raw_data", ""),
                        now,
                    ))
                conn.executemany("""
                    INSERT INTO normalized_logs (
                        host_id, hostname, log_source, event_id, event_type,
                        event_label, mitre_attack, severity, timestamp,
                        source_ip, source_hostname, target_ip, target_hostname,
                        user_name, user_domain, logon_session, process_name,
                        process_pid, parent_process_name, parent_process_pid,
                        command_line, object_name, tags, description, raw_data, created_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, data)
                conn.commit()
                return len(data)
        except Exception as e:
            logger.error("NormalizedLog.batch_create failed: %s", e)
            return 0

    @staticmethod
    def search(host_id: Optional[int] = None, hostname: Optional[str] = None,
               event_id: Optional[int] = None, event_type: Optional[str] = None,
               severity: Optional[str] = None,
               source_ip: Optional[str] = None, user_name: Optional[str] = None,
               process_name: Optional[str] = None,
               logon_session: Optional[str] = None,
               tag: Optional[str] = None,
               keyword: Optional[str] = None,
               date_from: Optional[str] = None, date_to: Optional[str] = None,
               log_source: Optional[str] = None,
               sort: str = "timestamp DESC", page: int = 1, page_size: int = 50,
               allowed_host_ids: Optional[set[int]] = None) -> dict:
        """多维度检索日志.

        Args:
            allowed_host_ids: ACL 可见主机集合（None=全量；空集合=WHERE 1=0）.
        """
        from app.services.time_utils import parse_client_time

        try:
            conditions = []
            params = []

            if host_id is not None:
                conditions.append("host_id=?")
                params.append(host_id)
            if allowed_host_ids is not None:
                if not allowed_host_ids:
                    conditions.append("1=0")  # 空可见集合 → 无结果
                else:
                    placeholders = ",".join("?" for _ in allowed_host_ids)
                    conditions.append(f"host_id IN ({placeholders})")
                    params.extend(sorted(allowed_host_ids))
            if hostname:
                conditions.append("hostname LIKE ?")
                params.append(f"%{hostname}%")
            if event_id is not None:
                conditions.append("event_id=?")
                params.append(event_id)
            if event_type:
                types = event_type.split(",")
                placeholders = ",".join("?" for _ in types)
                conditions.append(f"event_type IN ({placeholders})")
                params.extend(types)
            if severity:
                sevs = severity.split(",")
                placeholders = ",".join("?" for _ in sevs)
                conditions.append(f"severity IN ({placeholders})")
                params.extend(sevs)
            if source_ip:
                conditions.append("source_ip=?")
                params.append(source_ip)
            if user_name:
                conditions.append("user_name LIKE ?")
                params.append(f"%{user_name}%")
            if process_name:
                conditions.append("process_name LIKE ?")
                params.append(f"%{process_name}%")
            if logon_session:
                conditions.append("logon_session=?")
                params.append(logon_session)
            if tag:
                conditions.append("tags LIKE ?")
                params.append(f"%{tag}%")
            if log_source:
                conditions.append("log_source=?")
                params.append(log_source)
            if keyword:
                conditions.append("(description LIKE ? OR command_line LIKE ? OR process_name LIKE ?)")
                kw = f"%{keyword}%"
                params.extend([kw, kw, kw])
            if date_from:
                conditions.append("timestamp >= ?")
                params.append(parse_client_time(date_from))
            if date_to:
                conditions.append("timestamp <= ?")
                params.append(parse_client_time(date_to))

            where = " WHERE " + " AND ".join(conditions) if conditions else ""

            with get_connection() as conn:
                total = conn.execute(f"SELECT COUNT(*) FROM normalized_logs{where}", params).fetchone()[0]
                offset = (page - 1) * page_size
                sort_clause = sort or "timestamp DESC"
                rows = conn.execute(
                    f"SELECT * FROM normalized_logs{where} ORDER BY {sort_clause} LIMIT ? OFFSET ?",
                    params + [page_size, offset]
                ).fetchall()
                items = [dict(r) for r in rows]
                return {"items": items, "total": total, "page": page, "page_size": page_size}
        except Exception as e:
            logger.error("NormalizedLog.search failed: %s", e)
            return {"items": [], "total": 0, "page": page, "page_size": page_size}

    @staticmethod
    def get_stats(host_id: Optional[int] = None, allowed_host_ids: Optional[set[int]] = None) -> dict:
        """日志统计.

        Args:
            allowed_host_ids: ACL 可见主机集合（None=全量；空集合=返回空统计）.
        """
        try:
            where_parts = []
            params = []
            if host_id:
                where_parts.append("host_id=?")
                params.append(host_id)
            if allowed_host_ids is not None:
                if not allowed_host_ids:
                    return {"total": 0, "by_severity": {}, "by_type": {}, "top_ips": [], "top_users": []}
                placeholders = ",".join("?" for _ in allowed_host_ids)
                where_parts.append(f"host_id IN ({placeholders})")
                params.extend(sorted(allowed_host_ids))
            where = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""

            with get_connection() as conn:
                total = conn.execute(
                    f"SELECT COUNT(*) FROM normalized_logs{where}", params
                ).fetchone()[0]
                by_severity = dict(conn.execute(
                    f"SELECT severity, COUNT(*) FROM normalized_logs{where} GROUP BY severity", params
                ).fetchall())
                by_type = dict(conn.execute(
                    f"SELECT event_type, COUNT(*) FROM normalized_logs{where} GROUP BY event_type ORDER BY COUNT(*) DESC LIMIT 15",
                    params
                ).fetchall())
                top_ips = [{"ip": r[0], "count": r[1]} for r in conn.execute(
                    f"SELECT source_ip, COUNT(*) FROM normalized_logs WHERE source_ip<>''{(' AND ' + ' AND '.join(where_parts)) if where_parts else ''} GROUP BY source_ip ORDER BY COUNT(*) DESC LIMIT 10",
                    params
                ).fetchall()]
                top_users = [{"user": r[0], "count": r[1]} for r in conn.execute(
                    f"SELECT user_name, COUNT(*) FROM normalized_logs WHERE user_name<>''{(' AND ' + ' AND '.join(where_parts)) if where_parts else ''} GROUP BY user_name ORDER BY COUNT(*) DESC LIMIT 10",
                    params
                ).fetchall()]

                return {
                    "total": total,
                    "by_severity": by_severity,
                    "by_type": by_type,
                    "top_ips": top_ips,
                    "top_users": top_users,
                }
        except Exception as e:
            logger.error("NormalizedLog.get_stats failed: %s", e)
            return {"total": 0, "by_severity": {}, "by_type": {}, "top_ips": [], "top_users": []}

    @staticmethod
    def get_timeline(host_id: Optional[int] = None, interval: str = "hour",
                     date_from: Optional[str] = None, date_to: Optional[str] = None,
                     allowed_host_ids: Optional[set[int]] = None) -> list:
        """时间线聚合（使用 COALESCE 以 created_at 兜底空 timestamp）.

        Args:
            allowed_host_ids: ACL 可见主机集合（None=全量；空集合=返回空）.
        """
        from app.services.time_utils import parse_client_time

        try:
            conditions = []
            params = []
            if host_id is not None:
                conditions.append("host_id=?")
                params.append(host_id)
            if allowed_host_ids is not None:
                if not allowed_host_ids:
                    return []
                placeholders = ",".join("?" for _ in allowed_host_ids)
                conditions.append(f"host_id IN ({placeholders})")
                params.extend(sorted(allowed_host_ids))
            time_col = "COALESCE(NULLIF(timestamp,''), created_at)"
            if date_from:
                conditions.append(f"{time_col} >= ?")
                params.append(parse_client_time(date_from))
            if date_to:
                conditions.append(f"{time_col} <= ?")
                params.append(parse_client_time(date_to))

            where = " AND ".join(conditions)
            where_clause = f" WHERE {where}" if where else ""

            with get_connection() as conn:
                if interval == "day":
                    fmt = "%Y-%m-%d"
                else:
                    fmt = "%Y-%m-%d %H:00"
                rows = conn.execute(
                    f"""SELECT strftime('{fmt}', {time_col}) as bucket,
                               COUNT(*) as cnt, severity
                        FROM normalized_logs{where_clause}
                        GROUP BY bucket, severity ORDER BY bucket""",
                    params
                ).fetchall()
                trend = {}
                for r in rows:
                    b = r["bucket"]
                    if b not in trend:
                        trend[b] = {"bucket": b, "label": b[-5:], "critical": 0, "high": 0, "medium": 0, "total": 0}
                    sev = r["severity"]
                    if sev in ("critical", "high", "medium", "low"):
                        trend[b][sev] = trend[b].get(sev, 0) + r["cnt"]
                    trend[b]["total"] += r["cnt"]
                result = sorted(trend.values(), key=lambda x: x["bucket"])
                # 至少返回最近24小时的数据（补0）
                if not result:
                    from datetime import datetime, timedelta
                    now = datetime.now()
                    for i in range(23, -1, -1):
                        d = (now - timedelta(hours=i)).strftime("%m-%d %H:00")
                        result.append({"bucket": d, "label": d[-5:], "critical": 0, "high": 0, "medium": 0, "total": 0})
                return result
        except Exception as e:
            logger.error("NormalizedLog.get_timeline failed: %s", e)
            return []

    @staticmethod
    def get_session(logon_session: str, allowed_host_ids: Optional[set[int]] = None) -> list:
        """按 Logon Session 查询所有事件（ACL 注入可选）。"""
        return NormalizedLog.search(
            logon_session=logon_session, sort="timestamp ASC",
            allowed_host_ids=allowed_host_ids,
        )["items"]

    @staticmethod
    def pivot(field: str, value: str, host_id: Optional[int] = None,
              allowed_host_ids: Optional[set[int]] = None) -> list:
        """点击跳转聚合.

        Args:
            field: source_ip | user_name | process_name | event_type | hostname
            value: 筛选值
            host_id: 可选项，限定主机范围
            allowed_host_ids: ACL 可见主机集合（None=全量；空集合=返回空）.
        """
        try:
            conditions = [f"{field}=?"]
            params = [value]
            if host_id is not None:
                conditions.append("host_id=?")
                params.append(host_id)
            if allowed_host_ids is not None:
                if not allowed_host_ids:
                    return []
                placeholders = ",".join("?" for _ in allowed_host_ids)
                conditions.append(f"host_id IN ({placeholders})")
                params.extend(sorted(allowed_host_ids))
            where = " AND ".join(conditions)

            with get_connection() as conn:
                rows = conn.execute(
                    f"""SELECT event_type, severity, COUNT(*) as cnt,
                               MIN(timestamp) as first_seen, MAX(timestamp) as last_seen
                        FROM normalized_logs WHERE {where}
                        GROUP BY event_type, severity ORDER BY cnt DESC""",
                    params
                ).fetchall()
                return [dict(r) for r in rows]
        except Exception as e:
            logger.error("NormalizedLog.pivot failed: %s", e)
            return []

    @staticmethod
    def get_brute_force(min_attempts: int = 10, window_minutes: int = 5,
                        host_id: Optional[int] = None,
                        allowed_host_ids: Optional[set[int]] = None) -> list:
        """暴破攻击检测.

        Args:
            allowed_host_ids: ACL 可见主机集合（None=全量；空集合=返回空）.
        """
        try:
            conditions = ["event_id=4625"]
            params = []
            if host_id is not None:
                conditions.append("host_id=?")
                params.append(host_id)
            if allowed_host_ids is not None:
                if not allowed_host_ids:
                    return []
                placeholders = ",".join("?" for _ in allowed_host_ids)
                conditions.append(f"host_id IN ({placeholders})")
                params.extend(sorted(allowed_host_ids))

            with get_connection() as conn:
                rows = conn.execute(
                    f"""SELECT source_ip, user_name, COUNT(*) as attempts,
                               MIN(timestamp) as first_seen, MAX(timestamp) as last_seen
                        FROM normalized_logs WHERE {' AND '.join(conditions)}
                        GROUP BY source_ip, user_name
                        HAVING attempts >= ?""",
                    params + [min_attempts]
                ).fetchall()
                return [dict(r) for r in rows if dict(r).get("source_ip")]
        except Exception as e:
            logger.error("NormalizedLog.get_brute_force failed: %s", e)
            return []
