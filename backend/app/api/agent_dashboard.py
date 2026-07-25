"""智能体维度聚合看板 API — F1（§4.1）.

聚合 agent_runs / agent_run_steps / hitl_approvals，固化口径返回
{ running_agents, success_rate, pending_hitl, recent_runs, trend }。
纯聚合，无新表。

注册：app.include_router(agent_dashboard.router, prefix="/api/agents")
  → GET /api/agents/dashboard
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.database import get_connection
from app.services.auth_service import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()


def _parse_range(range_str: Optional[str]) -> int:
    """将 range 参数解析为天数（默认 7）。支持 '7d' / '24h' / 纯数字。"""
    range_str = (range_str or "7d").strip().lower()
    try:
        if range_str.endswith("d"):
            return max(1, int(range_str[:-1]))
        if range_str.endswith("h"):
            hours = int(range_str[:-1])
            return max(1, max(1, hours // 24))
    except ValueError:
        return 7
    try:
        return max(1, int(range_str))
    except ValueError:
        return 7


@router.get("/dashboard")
def agent_dashboard(
    time_range: str = Query("7d", alias="range", description="时间范围: 7d / 30d / 24h"),
    user: dict = Depends(get_current_user),
):
    """聚合智能体维度看板（§4.1 固化口径）。

    Returns:
        { running_agents, success_rate, pending_hitl, recent_runs, trend }
    """
    days = _parse_range(time_range)
    now = datetime.now()
    cutoff = (now - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

    try:
        with get_connection() as conn:
            running_agents = conn.execute(
                "SELECT COUNT(*) FROM agent_runs "
                "WHERE status IN ('running','waiting_hitl')"
            ).fetchone()[0]

            completed = conn.execute(
                "SELECT COUNT(*) FROM agent_runs "
                "WHERE status='completed' AND created_at >= ?",
                (cutoff,),
            ).fetchone()[0]
            failed = conn.execute(
                "SELECT COUNT(*) FROM agent_runs "
                "WHERE status='failed' AND created_at >= ?",
                (cutoff,),
            ).fetchone()[0]
            pending_hitl = conn.execute(
                "SELECT COUNT(*) FROM hitl_approvals WHERE status='pending'"
            ).fetchone()[0]

            total = completed + failed
            success_rate = round(100.0 * completed / total, 1) if total > 0 else 0.0

            # 趋势：按天分组每日成功率
            trend: list[dict] = []
            for i in range(days - 1, -1, -1):
                day_start = (now - timedelta(days=i)).strftime("%Y-%m-%d 00:00:00")
                day_end = (now - timedelta(days=i - 1)).strftime("%Y-%m-%d 00:00:00")
                c = conn.execute(
                    "SELECT COUNT(*) FROM agent_runs "
                    "WHERE status='completed' AND created_at >= ? AND created_at < ?",
                    (day_start, day_end),
                ).fetchone()[0]
                f = conn.execute(
                    "SELECT COUNT(*) FROM agent_runs "
                    "WHERE status='failed' AND created_at >= ? AND created_at < ?",
                    (day_start, day_end),
                ).fetchone()[0]
                denom = c + f
                rate = round(100.0 * c / denom, 1) if denom > 0 else 0.0
                ts = (now - timedelta(days=i)).strftime("%Y-%m-%d")
                trend.append({"ts": ts, "success_rate": rate})

            rows = conn.execute(
                "SELECT * FROM agent_runs ORDER BY created_at DESC LIMIT 10"
            ).fetchall()
        recent_runs = [dict(r) for r in rows]
        return {
            "code": 0,
            "data": {
                "running_agents": running_agents,
                "success_rate": success_rate,
                "pending_hitl": pending_hitl,
                "recent_runs": recent_runs,
                "trend": trend,
            },
            "message": "success",
        }
    except Exception as exc:
        logger.exception("agent_dashboard error")
        raise HTTPException(status_code=500, detail=str(exc))
