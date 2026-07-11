"""AI审计日志模型 — ai_audit_log 表 CRUD 操作."""

import logging
from typing import Any, Optional

from app.database import get_connection

logger = logging.getLogger(__name__)


class AiAuditLog:
    """AI调用审计日志模型.

    记录每次AI API调用的详细信息，包括token用量、延迟、错误等，
    用于成本核算、问题排查和安全审计.
    """

    @staticmethod
    def create(
        host_id: Optional[int] = None,
        host_name: str = "",
        profile_id: Optional[int] = None,
        profile_name: str = "",
        model_name: str = "",
        status: str = "success",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        latency_ms: int = 0,
        masked_mode: int = 0,
        prompt: str = "",
        response: str = "",
        error_message: Optional[str] = None,
        ip_address: str = "",
        user_id: Optional[int] = None,
    ) -> dict:
        """创建审计日志记录."""
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO ai_audit_log
                (host_id, host_name, profile_id, profile_name, model_name,
                 status, prompt_tokens, completion_tokens, total_tokens,
                 latency_ms, masked_mode, prompt, response,
                 error_message, ip_address, user_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    host_id, host_name, profile_id, profile_name, model_name,
                    status, prompt_tokens, completion_tokens, total_tokens,
                    latency_ms, masked_mode, prompt, response,
                    error_message, ip_address, user_id,
                ),
            )
            log_id = cursor.lastrowid
            logger.info(
                "AiAuditLog.create: id=%d, host=%s, model=%s, status=%s, tokens=(%d,%d,%d), latency=%dms",
                log_id, host_name or f"host_{host_id}", model_name, status,
                prompt_tokens, completion_tokens, total_tokens, latency_ms,
            )
        return AiAuditLog.get_by_id(log_id)

    @staticmethod
    def get_by_id(log_id: int) -> Optional[dict]:
        """根据ID获取审计日志."""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM ai_audit_log WHERE id = ?", (log_id,)
            ).fetchone()
            return dict(row) if row else None

    @staticmethod
    def list_all(
        page: int = 1,
        page_size: int = 20,
        host_id: Optional[int] = None,
        profile_id: Optional[int] = None,
        status: Optional[str] = None,
        model_name: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        masked_mode: Optional[int] = None,
        order_by: str = "created_at DESC",
    ) -> dict:
        """列出审计日志（支持分页和筛选）.

        Args:
            page: 页码（从1开始）.
            page_size: 每页条数.
            host_id: 按主机ID筛选.
            profile_id: 按配置Profile ID筛选.
            status: 按状态筛选.
            model_name: 按模型名称筛选.
            start_date: 起始日期（ISO格式）.
            end_date: 截止日期（ISO格式）.
            masked_mode: 按脱敏模式筛选（0或1）.
            order_by: 排序方式.

        Returns:
            {"items": [...], "total": int, "page": int, "page_size": int}
        """
        conditions: list[str] = []
        params: list[Any] = []

        if host_id is not None:
            conditions.append("host_id = ?")
            params.append(host_id)
        if profile_id is not None:
            conditions.append("profile_id = ?")
            params.append(profile_id)
        if status:
            conditions.append("status = ?")
            params.append(status)
        if model_name:
            conditions.append("model_name = ?")
            params.append(model_name)
        if masked_mode is not None:
            conditions.append("masked_mode = ?")
            params.append(masked_mode)
        if start_date:
            conditions.append("created_at >= ?")
            params.append(start_date)
        if end_date:
            conditions.append("created_at <= ?")
            params.append(end_date)

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        with get_connection() as conn:
            # 查总数
            count_sql = f"SELECT COUNT(*) as cnt FROM ai_audit_log {where_clause}"
            total = conn.execute(count_sql, params).fetchone()["cnt"]

            # 查分页数据
            offset = (page - 1) * page_size
            data_sql = (
                f"SELECT * FROM ai_audit_log {where_clause} "
                f"ORDER BY {order_by} LIMIT ? OFFSET ?"
            )
            rows = conn.execute(data_sql, params + [page_size, offset]).fetchall()

        return {
            "items": [dict(row) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    @staticmethod
    def get_token_stats(
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        profile_id: Optional[int] = None,
    ) -> dict:
        """获取Token使用统计.

        Returns:
            {
                "total_prompt_tokens": int,
                "total_completion_tokens": int,
                "total_tokens": int,
                "total_calls": int,
                "success_calls": int,
                "failed_calls": int,
                "avg_latency_ms": int,
                "total_cost_estimate": str  (简单估算)
            }
        """
        conditions: list[str] = []
        params: list[Any] = []

        if profile_id is not None:
            conditions.append("profile_id = ?")
            params.append(profile_id)
        if start_date:
            conditions.append("created_at >= ?")
            params.append(start_date)
        if end_date:
            conditions.append("created_at <= ?")
            params.append(end_date)

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        with get_connection() as conn:
            stats = conn.execute(
                f"""
                SELECT
                    COALESCE(SUM(prompt_tokens), 0) as total_prompt_tokens,
                    COALESCE(SUM(completion_tokens), 0) as total_completion_tokens,
                    COALESCE(SUM(total_tokens), 0) as total_tokens,
                    COUNT(*) as total_calls,
                    SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success_calls,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed_calls,
                    COALESCE(AVG(latency_ms), 0) as avg_latency_ms
                FROM ai_audit_log {where_clause}
                """,
                params,
            ).fetchone()

        result = dict(stats)
        result["avg_latency_ms"] = int(result["avg_latency_ms"])

        # 简单的成本估算（假设 GPT-4o 定价：输入 $2.5/M, 输出 $10/M）
        prompt_cost = result["total_prompt_tokens"] / 1_000_000 * 2.5
        completion_cost = result["total_completion_tokens"] / 1_000_000 * 10.0
        total_cost = prompt_cost + completion_cost
        result["total_cost_estimate"] = f"${total_cost:.4f}"

        return result

    @staticmethod
    def get_token_summary(group_by: str = "daily") -> list[dict]:
        """获取Token使用汇总（按天/按模型/按Profile汇总）.

        Args:
            group_by: 汇总维度，支持 "daily", "model", "profile".

        Returns:
            汇总数据列表.
        """
        group_config = {
            "daily": {
                "group_field": "DATE(created_at)",
                "label": "date",
                "order": "DATE(created_at) DESC",
            },
            "model": {
                "group_field": "model_name",
                "label": "model_name",
                "order": "total_tokens DESC",
            },
            "profile": {
                "group_field": "profile_name",
                "label": "profile_name",
                "order": "total_tokens DESC",
            },
        }

        config = group_config.get(group_by, group_config["daily"])
        group_field = config["group_field"]
        label = config["label"]
        order = config["order"]

        with get_connection() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    {group_field} as {label},
                    COALESCE(SUM(prompt_tokens), 0) as prompt_tokens,
                    COALESCE(SUM(completion_tokens), 0) as completion_tokens,
                    COALESCE(SUM(total_tokens), 0) as total_tokens,
                    COUNT(*) as call_count,
                    COALESCE(AVG(latency_ms), 0) as avg_latency_ms
                FROM ai_audit_log
                WHERE status = 'success'
                GROUP BY {group_field}
                ORDER BY {order}
                LIMIT 100
                """
            ).fetchall()

        return [dict(row) for row in rows]
