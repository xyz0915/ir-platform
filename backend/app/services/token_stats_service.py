"""Token 消耗统计服务.

从 ai_audit_log 表聚合数据，提供按日/按月统计和汇总卡片数据.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from app.database import get_connection

logger = logging.getLogger(__name__)


class TokenStatsService:
    """Token 消耗统计服务.

    提供多维度的 Token 使用统计：按日、按月、汇总。
    所有统计基于 ai_audit_log 表。
    """

    @staticmethod
    def get_daily_stats(days: int = 30, group_by: Optional[str] = None) -> list[dict]:
        """获取按日期聚合的 Token 消耗统计.

        Args:
            days: 统计最近 N 天的数据.
            group_by: 分组维度 — "endpoint" 按endpoint分组, "model" 按model_name分组.

        Returns:
            默认: [{date, total_tokens, prompt_tokens, completion_tokens, count}, ...]
            按分组: [{date, endpoint/model_name, total_tokens, ...}, ...]
            按日期升序排列（旧→新）.
        """
        start_date = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")

        if group_by == "endpoint":
            with get_connection() as conn:
                rows = conn.execute(
                    """
                    SELECT
                        DATE(created_at) as date,
                        endpoint,
                        COALESCE(SUM(prompt_tokens), 0) as prompt_tokens,
                        COALESCE(SUM(completion_tokens), 0) as completion_tokens,
                        COALESCE(SUM(total_tokens), 0) as total_tokens,
                        COUNT(*) as count
                    FROM ai_audit_log
                    WHERE created_at >= ?
                    GROUP BY DATE(created_at), endpoint
                    ORDER BY date ASC, endpoint
                    """,
                    (start_date,),
                ).fetchall()
            return [dict(row) for row in rows]

        if group_by == "model":
            with get_connection() as conn:
                rows = conn.execute(
                    """
                    SELECT
                        DATE(created_at) as date,
                        model_name,
                        COALESCE(SUM(prompt_tokens), 0) as prompt_tokens,
                        COALESCE(SUM(completion_tokens), 0) as completion_tokens,
                        COALESCE(SUM(total_tokens), 0) as total_tokens,
                        COUNT(*) as count
                    FROM ai_audit_log
                    WHERE created_at >= ?
                    GROUP BY DATE(created_at), model_name
                    ORDER BY date ASC, model_name
                    """,
                    (start_date,),
                ).fetchall()
            return [dict(row) for row in rows]

        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT
                    DATE(created_at) as date,
                    COALESCE(SUM(prompt_tokens), 0) as prompt_tokens,
                    COALESCE(SUM(completion_tokens), 0) as completion_tokens,
                    COALESCE(SUM(total_tokens), 0) as total_tokens,
                    COUNT(*) as count
                FROM ai_audit_log
                WHERE created_at >= ?
                GROUP BY DATE(created_at)
                ORDER BY date ASC
                """,
                (start_date,),
            ).fetchall()

        return [dict(row) for row in rows]

    @staticmethod
    def get_monthly_stats(months: int = 12) -> list[dict]:
        """获取按月聚合的 Token 消耗统计.

        Args:
            months: 统计最近 N 个月的数据.

        Returns:
            [{month, total_tokens, prompt_tokens, completion_tokens, count}, ...]
            按月份升序排列.
        """
        start_date = (datetime.utcnow() - timedelta(days=months * 31)).strftime("%Y-%m-01")

        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT
                    strftime('%Y-%m', created_at) as month,
                    COALESCE(SUM(prompt_tokens), 0) as prompt_tokens,
                    COALESCE(SUM(completion_tokens), 0) as completion_tokens,
                    COALESCE(SUM(total_tokens), 0) as total_tokens,
                    COUNT(*) as count,
                    COALESCE(AVG(latency_ms), 0) as avg_latency_ms
                FROM ai_audit_log
                WHERE created_at >= ?
                GROUP BY strftime('%Y-%m', created_at)
                ORDER BY month ASC
                """,
                (start_date,),
            ).fetchall()

        return [dict(row) for row in rows]

    @staticmethod
    def get_summary() -> dict:
        """获取汇总统计卡片数据.

        包含总计、本月、成功率等关键指标.

        Returns:
            {
                total_tokens: int,
                total_calls: int,
                avg_latency_ms: float,
                success_rate: float (0.0 ~ 1.0),
                this_month_tokens: int,
                this_month_calls: int,
            }
        """
        this_month_start = datetime.utcnow().strftime("%Y-%m-01")

        with get_connection() as conn:
            # 总计
            total_row = conn.execute(
                """
                SELECT
                    COALESCE(SUM(total_tokens), 0) as total_tokens,
                    COUNT(*) as total_calls,
                    SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success_calls,
                    COALESCE(AVG(latency_ms), 0) as avg_latency_ms
                FROM ai_audit_log
                """
            ).fetchone()

            # 本月
            month_row = conn.execute(
                """
                SELECT
                    COALESCE(SUM(total_tokens), 0) as month_tokens,
                    COUNT(*) as month_calls
                FROM ai_audit_log
                WHERE created_at >= ?
                """,
                (this_month_start,),
            ).fetchone()

        total = dict(total_row) if total_row else {}
        month = dict(month_row) if month_row else {}

        total_tokens = int(total.get("total_tokens") or 0)
        total_calls = int(total.get("total_calls") or 0)
        success_calls = int(total.get("success_calls") or 0)
        avg_latency_ms = float(total.get("avg_latency_ms") or 0)

        # 成功率
        success_rate = round(success_calls / total_calls, 4) if total_calls > 0 else 0.0

        # 按 endpoint 分类统计
        with get_connection() as conn:
            endpoint_rows = conn.execute(
                """
                SELECT
                    endpoint,
                    COALESCE(SUM(total_tokens), 0) as total_tokens,
                    COUNT(*) as total_calls
                FROM ai_audit_log
                WHERE endpoint IS NOT NULL AND endpoint != ''
                GROUP BY endpoint
                ORDER BY total_calls DESC
                """
            ).fetchall()
        by_endpoint = [dict(r) for r in endpoint_rows]

        return {
            "total_tokens": total_tokens,
            "total_calls": total_calls,
            "avg_latency_ms": round(avg_latency_ms, 1),
            "success_rate": success_rate,
            "this_month_tokens": int(month.get("month_tokens", 0)),
            "this_month_calls": int(month.get("month_calls", 0)),
            "by_endpoint": by_endpoint,
        }
