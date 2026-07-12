"""全局态势仪表盘 API — 聚合查询各维度数据."""
import json
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter
from app.database import get_connection

logger = logging.getLogger(__name__)
router = APIRouter(tags=["仪表盘"])


@router.get("/dashboard/stats")
def dashboard_stats():
    """聚合仪表盘全局统计数据."""
    result = {
        "metrics": {},
        "trend": {},
        "risk_distribution": {},
        "recent_alerts": [],
        "recent_hosts": [],
        "rule_top": [],
    }

    try:
        with get_connection() as db:
            # ── 指标卡片 ──
            # 待处理告警: abnormal_processes 中 severity=critical/high 且未关联 closed case
            alert_row = db.execute(
                "SELECT COUNT(*) FROM abnormal_processes a "
                "JOIN hosts h ON a.host_id = h.id "
                "JOIN cases c ON h.case_id = c.id "
                "WHERE c.status != 'closed' AND a.severity IN ('critical', 'high')"
            ).fetchone()
            result["metrics"]["pending_alerts"] = alert_row[0] if alert_row else 0

            # 严重告警数（需立即处置）
            critical_row = db.execute(
                "SELECT COUNT(*) FROM abnormal_processes WHERE severity='critical'"
            ).fetchone()
            result["metrics"]["critical_alerts"] = critical_row[0] if critical_row else 0

            # 活跃案件
            case_row = db.execute(
                "SELECT COUNT(*) FROM cases WHERE status != 'closed'"
            ).fetchone()
            result["metrics"]["active_cases"] = case_row[0] if case_row else 0

            # 今日新增案件
            today = datetime.now().strftime("%Y-%m-%d")
            today_case = db.execute(
                "SELECT COUNT(*) FROM cases WHERE created_at >= ?", [today]
            ).fetchone()
            result["metrics"]["new_cases_today"] = today_case[0] if today_case else 0

            # 已采集主机
            host_row = db.execute("SELECT COUNT(*) FROM hosts").fetchone()
            result["metrics"]["total_hosts"] = host_row[0] if host_row else 0

            # 待分析主机
            pending_host = db.execute(
                "SELECT COUNT(*) FROM hosts WHERE status='pending'"
            ).fetchone()
            result["metrics"]["pending_hosts"] = pending_host[0] if pending_host else 0

            # 最近 24h 新增主机
            yesterday = (datetime.now() - timedelta(days=1)).isoformat()
            recent_host = db.execute(
                "SELECT COUNT(*) FROM hosts WHERE created_at >= ?", [yesterday]
            ).fetchone()
            result["metrics"]["recent_hosts_24h"] = recent_host[0] if recent_host else 0

            # 规则命中数 (使用 hit_count 字段，如无则统计 abnormal_processes)
            try:
                rule_hits = db.execute(
                    "SELECT COALESCE(SUM(hit_count), 0) FROM rules"
                ).fetchone()
                result["metrics"]["total_rule_hits"] = rule_hits[0] if rule_hits else 0
            except Exception:
                result["metrics"]["total_rule_hits"] = 0

            # 活跃规则数
            try:
                active_rules = db.execute(
                    "SELECT COUNT(*) FROM rules WHERE enabled=1 AND hit_count>0"
                ).fetchone()
                result["metrics"]["active_rules"] = active_rules[0] if active_rules else 0
            except Exception:
                result["metrics"]["active_rules"] = 0

            # AI 分析可用率模拟（统计 analysis_results 有内容的占比）
            ai_row = db.execute(
                "SELECT COUNT(*) FROM ai_analysis_reports WHERE created_at >= ?",
                [yesterday]
            ).fetchone()
            result["metrics"]["ai_analyses_recent"] = ai_row[0] if ai_row else 0

            # ── 案件趋势（最近 7 天） ──
            trend_labels = []
            trend_critical = []
            trend_high = []
            trend_medium = []
            for i in range(6, -1, -1):
                day = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
                label = (datetime.now() - timedelta(days=i)).strftime("%m/%d")
                trend_labels.append(label)
                # 各严重度的异常进程数
                for sev, arr in [("critical", trend_critical), ("high", trend_high), ("medium", trend_medium)]:
                    row = db.execute(
                        "SELECT COUNT(*) FROM abnormal_processes a "
                        "JOIN analysis_results ar ON a.host_id = ar.host_id "
                        "WHERE a.severity=? AND ar.analyzed_at >= ? AND ar.analyzed_at < ?",
                        [sev, day, (datetime.now() - timedelta(days=i - 1)).strftime("%Y-%m-%d")]
                    ).fetchone()
                    arr.append(row[0] if row else 0)
            result["trend"]["labels"] = trend_labels
            result["trend"]["critical"] = trend_critical
            result["trend"]["high"] = trend_high
            result["trend"]["medium"] = trend_medium

            # ── 规则命中趋势（最近 7 天） ──
            result["trend"]["rule_hits"] = [0] * 7  # 暂缺每天命中历史

            # ── 告警类别分布 ──
            type_rows = db.execute(
                "SELECT rule_name, COUNT(*) as cnt FROM abnormal_processes "
                "GROUP BY rule_name ORDER BY cnt DESC LIMIT 8"
            ).fetchall()
            type_data = []
            type_labels = []
            for row in type_rows:
                label = row[0] or "unknown"
                # 简化名称
                short = label.replace("_", " ").title()[:12]
                type_labels.append(short)
                type_data.append({"name": short, "value": row[1]})
            result["risk_distribution"]["types"] = type_data

            # ── 规则命中 Top 8 ──
            try:
                top_rules = db.execute(
                    "SELECT name, hit_count FROM rules WHERE enabled=1 AND hit_count>0 "
                    "ORDER BY hit_count DESC LIMIT 8"
                ).fetchall()
                max_hits = top_rules[0][1] if top_rules else 1
                result["rule_top"] = [
                    {"name": r[0], "hits": r[1], "pct": round(r[1] / max_hits * 100)}
                    for r in top_rules
                ]
            except Exception:
                result["rule_top"] = []

            # ── 最近采集主机 ──
            host_rows = db.execute(
                "SELECT h.hostname, h.ip_address, COALESCE(ar.risk_level, 'pending') as risk_level "
                "FROM hosts h LEFT JOIN analysis_results ar ON h.id = ar.host_id "
                "ORDER BY h.created_at DESC LIMIT 8"
            ).fetchall()
            result["recent_hosts"] = [
                {"hostname": r[0], "ip": r[1] or "N/A", "risk_level": r[2] or "pending"}
                for r in host_rows
            ]

            # ── 最近告警 ──
            alert_rows = db.execute(
                "SELECT a.process_name, a.reason, a.severity, h.hostname, a.pid, a.command_line, "
                "ar.analyzed_at "
                "FROM abnormal_processes a "
                "JOIN hosts h ON a.host_id = h.id "
                "LEFT JOIN analysis_results ar ON a.host_id = ar.host_id "
                "ORDER BY ar.analyzed_at DESC LIMIT 6"
            ).fetchall()
            for r in alert_rows:
                cmd = (r[5] or "")[:60]
                result["recent_alerts"].append({
                    "title": f"【{r[0] or '?'}】{(r[1] or '')[:40]}",
                    "host": r[3] or "?",
                    "pid": r[4],
                    "detail": cmd,
                    "severity": r[2] or "medium",
                    "time": r[6] or "",
                })

    except Exception as e:
        logger.error("仪表盘数据聚合失败: %s", e, exc_info=True)
        result["error"] = str(e)

    return result
