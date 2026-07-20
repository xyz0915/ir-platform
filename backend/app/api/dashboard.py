"""全局态势仪表盘 API — 聚合查询各维度数据（全数据驱动版本）. """
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Query
from app.database import get_connection

logger = logging.getLogger(__name__)
router = APIRouter(tags=["仪表盘"])

# 仪表盘缓存（TTL 60s，减少重复查询）
_dash_cache: dict[str, tuple[float, dict]] = {}
_DASH_CACHE_TTL = 60

# 告警类别 rule_name → 中文标签映射
_RULE_LABEL_MAP: dict[str, str] = {
    "powershell_encoded_command": "PowerShell 编码命令",
    "powershell_bypass_execution": "PowerShell 绕过",
    "certutil_download": "certutil 下载",
    "mshta_inline_script": "MSHTA 执行",
    "wmic_lolbin_execution": "WMIC 利用",
    "regsvr32_squiblydoo": "Regsvr32 绕过",
    "rundll32_suspicious": "Rundll32 可疑",
    "cscript_wscript_download": "脚本下载器",
    "cmd_powershell_chain": "CMD→PS 链",
    "bitsadmin_download": "Bitsadmin 下载",
    "msiexec_remote_lolbin": "MSIExec 远程",
    "msbuild_inline_task_execution": "MSBuild 内联",
    "dotnet_inline_compilation": "DotNet 编译",
    "orphan_process": "孤立进程",
    "suspicious_parent_child": "可疑父子进程",
    "unsigned_process": "未签名进程",
    "high_connection_count": "高连接数",
    "nc_netcat_listener": "Netcat 监听",
    "short_lived_shell": "短存活 Shell",
    "suspicious_scheduled_task_xml_exists": "计划任务异常",
    "suspicious_service_reg_exists": "服务注册异常",
    "webshell_activity": "WebShell 行为",
    "ransomware_behavior": "勒索软件行为",
}

_SEVERITY_TREND_MAP = {
    "critical": "critical", "high": "high", "medium": "medium",
}


def _label_for_rule(rule_name: str) -> str:
    """获取规则的中文标签."""
    if not rule_name:
        return "未知"
    key = rule_name.lower().replace(" ", "_").replace("-", "_")
    # 精确匹配优先
    if key in _RULE_LABEL_MAP:
        return _RULE_LABEL_MAP[key]
    # 前缀匹配
    for prefix, label in _RULE_LABEL_MAP.items():
        if key.startswith(prefix):
            return label
    # 最后手段: 用最后一个下划线后的词组
    parts = rule_name.split("_")
    short = " ".join(parts[-2:]).title() if len(parts) > 1 else parts[0].title()
    return short[:20]


@router.get("/dashboard/stats")
def dashboard_stats(
    time_range: str = Query("7d", alias="range", description="时间范围: 24h / 7d / 30d / all"),
):
    """聚合仪表盘全局统计数据（缓存 60s，减少重复查询）。"""
    key = f"dash:{time_range}"
    now = time.time()
    if key in _dash_cache:
        ts, data = _dash_cache[key]
        if now - ts < _DASH_CACHE_TTL:
            return data
    result = {
        "metrics": {},
        "trend": {},
        "risk_distribution": {},
        "recent_alerts": [],
        "recent_hosts": [],
        "rule_top": [],
    }

    # 计算时间范围
    now = datetime.now()
    if time_range == "24h":
        window_start = now - timedelta(hours=24)
        trend_days = 1
    elif time_range == "7d":
        window_start = now - timedelta(days=7)
        trend_days = 7
    elif time_range == "30d":
        window_start = now - timedelta(days=30)
        trend_days = 30
    else:
        window_start = datetime(2020, 1, 1)
        trend_days = 14  # 全部模式下最多展示 14 天

    yesterday = (now - timedelta(days=1)).isoformat()
    today_str = now.strftime("%Y-%m-%d")

    try:
        with get_connection() as db:

            # ── KPI 指标卡片 ──
            # 1. 待处理告警（未关闭案件下的 critical/high 异常进程）
            alert_row = db.execute(
                "SELECT COUNT(*) FROM abnormal_processes a "
                "JOIN hosts h ON a.host_id = h.id "
                "JOIN cases c ON h.case_id = c.id "
                "WHERE c.status != 'closed' AND a.severity IN ('critical','high')"
            ).fetchone()
            result["metrics"]["pending_alerts"] = alert_row[0] if alert_row else 0

            # 严重告警数
            critical_row = db.execute(
                "SELECT COUNT(*) FROM abnormal_processes WHERE severity='critical'"
            ).fetchone()
            result["metrics"]["critical_alerts"] = critical_row[0] if critical_row else 0

            # 较昨日变化
            yesterday_alerts = db.execute(
                "SELECT COUNT(*) FROM abnormal_processes a "
                "JOIN analysis_results ar ON a.host_id = ar.host_id "
                "WHERE a.severity IN ('critical','high') AND ar.analyzed_at >= ? AND ar.analyzed_at < ?",
                [yesterday, today_str]
            ).fetchone()
            day_before = db.execute(
                "SELECT COUNT(*) FROM abnormal_processes a "
                "JOIN analysis_results ar ON a.host_id = ar.host_id "
                "WHERE a.severity IN ('critical','high') AND ar.analyzed_at >= ? AND ar.analyzed_at < ?",
                [(now - timedelta(days=2)).isoformat(), yesterday]
            ).fetchone()
            ya = yesterday_alerts[0] if yesterday_alerts else 0
            db_ = day_before[0] if day_before else 0
            delta = ya - db_
            result["metrics"]["alert_trend"] = delta
            result["metrics"]["alert_trend_dir"] = "up" if delta > 0 else ("down" if delta < 0 else "flat")

            # 活跃案件
            case_row = db.execute(
                "SELECT COUNT(*) FROM cases WHERE status != 'closed'"
            ).fetchone()
            result["metrics"]["active_cases"] = case_row[0] if case_row else 0

            # 今日新增案件
            today_case = db.execute(
                "SELECT COUNT(*) FROM cases WHERE created_at >= ?", [today_str]
            ).fetchone()
            result["metrics"]["new_cases_today"] = today_case[0] if today_case else 0

            # 昨日新增案件增减
            yesterday_case = db.execute(
                "SELECT COUNT(*) FROM cases WHERE created_at >= ? AND created_at < ?",
                [yesterday, today_str]
            ).fetchone()
            yc = yesterday_case[0] if yesterday_case else 0
            result["metrics"]["cases_trend"] = (today_case[0] if today_case else 0) - yc

            # 已采集主机
            host_row = db.execute("SELECT COUNT(*) FROM hosts").fetchone()
            result["metrics"]["total_hosts"] = host_row[0] if host_row else 0

            # 待分析主机
            pending_host = db.execute(
                "SELECT COUNT(*) FROM hosts WHERE status='pending'"
            ).fetchone()
            result["metrics"]["pending_hosts"] = pending_host[0] if pending_host else 0

            # 最近 24h 新增主机
            recent_host_24h = db.execute(
                "SELECT COUNT(*) FROM hosts WHERE created_at >= ?", [yesterday]
            ).fetchone()
            result["metrics"]["recent_hosts_24h"] = recent_host_24h[0] if recent_host_24h else 0

            # 规则命中总数
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

            # 知识库条数（审核通过的）
            kb_row = db.execute(
                "SELECT COUNT(*) FROM knowledge_drafts WHERE status='approved' OR status='imported'"
            ).fetchone()
            kb_total = kb_row[0] if kb_row else 0
            result["metrics"]["kb_hits"] = kb_total

            # 知识库覆盖率：分析了 knowledge_hits 的主机占比
            try:
                total_analyzed = db.execute(
                    "SELECT COUNT(*) FROM analysis_results"
                ).fetchone()
                ta = total_analyzed[0] if total_analyzed else 0
                if ta > 0:
                    # 检查 details 中包含 knowledge_hit 或 knowledge_hits 的记录数
                    with_kh = db.execute(
                        "SELECT COUNT(*) FROM analysis_results WHERE details LIKE '%knowledge_hit%' OR details LIKE '%knowledge_hits%'"
                    ).fetchone()
                    wk = with_kh[0] if with_kh else 0
                    result["metrics"]["kb_coverage"] = round(wk / ta * 100)
                else:
                    result["metrics"]["kb_coverage"] = 0
            except Exception:
                result["metrics"]["kb_coverage"] = 0

            # AI 分析数（最近 24h）
            ai_row = db.execute(
                "SELECT COUNT(*) FROM ai_tasks WHERE completed_at >= ?", [yesterday]
            ).fetchone()
            result["metrics"]["ai_analyses_recent"] = ai_row[0] if ai_row else 0

            # AI 可用率（最近 7 天 completed / total）
            try:
                ai_total = db.execute(
                    "SELECT COUNT(*) FROM ai_tasks WHERE created_at >= ?",
                    [(now - timedelta(days=7)).isoformat()]
                ).fetchone()
                ai_ok = db.execute(
                    "SELECT COUNT(*) FROM ai_tasks WHERE status='completed' AND created_at >= ?",
                    [(now - timedelta(days=7)).isoformat()]
                ).fetchone()
                at = ai_total[0] if ai_total else 0
                ao = ai_ok[0] if ai_ok else 0
                result["metrics"]["ai_availability"] = round(ao / at * 100, 1) if at > 0 else 0
            except Exception:
                result["metrics"]["ai_availability"] = 0

            # AI 分析趋势
            try:
                ai_yesterday = db.execute(
                    "SELECT COUNT(*) FROM ai_tasks WHERE status='completed' AND completed_at >= ? AND completed_at < ?",
                    [(now - timedelta(days=1)).isoformat(), today_str]
                ).fetchone()
                ai_day_before = db.execute(
                    "SELECT COUNT(*) FROM ai_tasks WHERE status='completed' AND completed_at >= ? AND completed_at < ?",
                    [(now - timedelta(days=2)).isoformat(), (now - timedelta(days=1)).isoformat()]
                ).fetchone()
                aiy = ai_yesterday[0] if ai_yesterday else 0
                aid = ai_day_before[0] if ai_day_before else 0
                result["metrics"]["ai_trend"] = aiy - aid
            except Exception:
                result["metrics"]["ai_trend"] = 0

            # ── 案件趋势（按天聚合） ──
            trend_labels = []
            trend_critical = []
            trend_high = []
            trend_medium = []
            trend_rule_hits = []

            for i in range(trend_days - 1, -1, -1):
                day_start = (now - timedelta(days=i)).strftime("%Y-%m-%d")
                day_end = (now - timedelta(days=i - 1)).strftime("%Y-%m-%d")
                label = (now - timedelta(days=i)).strftime("%m/%d")
                trend_labels.append(label)

                for sev, arr in [("critical", trend_critical), ("high", trend_high), ("medium", trend_medium)]:
                    row = db.execute(
                        "SELECT COUNT(*) FROM abnormal_processes a "
                        "JOIN analysis_results ar ON a.host_id = ar.host_id "
                        "WHERE a.severity=? AND ar.analyzed_at >= ? AND ar.analyzed_at < ?",
                        [sev, day_start, day_end]
                    ).fetchone()
                    arr.append(row[0] if row else 0)

                # 规则命中趋势：用当天 abnormal_processes 总数代替（近似）
                hits_row = db.execute(
                    "SELECT COUNT(*) FROM abnormal_processes a "
                    "JOIN analysis_results ar ON a.host_id = ar.host_id "
                    "WHERE ar.analyzed_at >= ? AND ar.analyzed_at < ?",
                    [day_start, day_end]
                ).fetchone()
                trend_rule_hits.append(hits_row[0] if hits_row else 0)

            result["trend"]["labels"] = trend_labels
            result["trend"]["critical"] = trend_critical
            result["trend"]["high"] = trend_high
            result["trend"]["medium"] = trend_medium
            result["trend"]["rule_hits"] = trend_rule_hits

            # ── 告警类别分布 ──
            type_rows = db.execute(
                "SELECT rule_name, COUNT(*) as cnt FROM abnormal_processes "
                "GROUP BY rule_name ORDER BY cnt DESC LIMIT 8"
            ).fetchall()
            type_data = []
            for row in type_rows:
                name = row[0] or "unknown"
                label = _label_for_rule(name)
                type_data.append({"name": label, "value": row[1], "rule_name": name})
            result["risk_distribution"]["types"] = type_data

            # ── 规则命中 Top 8 ──
            try:
                top_rules = db.execute(
                    "SELECT name, hit_count, label FROM rules WHERE enabled=1 AND hit_count>0 "
                    "ORDER BY hit_count DESC LIMIT 8"
                ).fetchall()
                max_hits = top_rules[0][1] if top_rules else 1
                result["rule_top"] = [
                    {
                        "name": r[2] or r[0],  # 优先用中文 label
                        "hits": r[1],
                        "pct": round(r[1] / max_hits * 100),
                    }
                    for r in top_rules
                ]
            except Exception:
                result["rule_top"] = []

            # ── 最近主机（含 host_id） ──
            host_rows = db.execute(
                "SELECT h.id, h.hostname, h.ip_address, COALESCE(ar.risk_level, 'pending') as risk_level "
                "FROM hosts h LEFT JOIN analysis_results ar ON h.id = ar.host_id "
                "ORDER BY h.created_at DESC LIMIT 8"
            ).fetchall()
            result["recent_hosts"] = [
                {
                    "id": r[0],
                    "hostname": r[1],
                    "ip": r[2] or "N/A",
                    "risk_level": r[3] or "pending",
                }
                for r in host_rows
            ]

            # ── 最近告警 ──
            alert_rows = db.execute(
                "SELECT a.process_name, a.reason, a.severity, h.hostname, a.pid, a.command_line, "
                "COALESCE(ar.analyzed_at, a.id) as sort_key "
                "FROM abnormal_processes a "
                "JOIN hosts h ON a.host_id = h.id "
                "LEFT JOIN analysis_results ar ON a.host_id = ar.host_id "
                "ORDER BY sort_key DESC LIMIT 6"
            ).fetchall()
            for r in alert_rows:
                proc_name = r[0] or "Unknown"
                reason = (r[1] or "")[:40]
                cmd = (r[5] or "")[:60]
                result["recent_alerts"].append({
                    "title": f"【{proc_name}】{reason}" if reason else f"【{proc_name}】",
                    "host": r[3] or "?",
                    "pid": r[4],
                    "detail": cmd,
                    "severity": r[2] or "medium",
                    "time": str(r[6] or ""),
                })

    except Exception as e:
        logger.error("仪表盘数据聚合失败: %s", e, exc_info=True)
        result["error"] = str(e)

    result["range"] = time_range
    _dash_cache[key] = (time.time(), result)
    return result
