"""AI 高级关联功能 API.

包含: 语义降噪 & 事件归并 / 自然语言指挥台 / 攻击故事讲述 / 误报自学习 / 预测预警
"""

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from app.services.auth_service import get_current_user
from app.database import get_connection

logger = logging.getLogger(__name__)
router = APIRouter()

# ─────────────────────────────────────────────
# 1. 语义级告警降噪与事件归并
# ─────────────────────────────────────────────

@router.post("/ai/correlate-incidents")
def correlate_incidents(
    host_id: Optional[int] = Query(None),
    time_window_minutes: int = Query(60),
    current_user: dict = Depends(get_current_user),
):
    """基于已有告警数据 + 时间窗口 + 攻击链自动归并事件."""
    from app.models.incident import IncidentCorrelation
    from app.database import get_connection
    from collections import defaultdict

    # 直接 SQL 获取告警
    with get_connection() as conn:
        if host_id:
            rows = conn.execute(
                "SELECT * FROM alerts WHERE host_id=? ORDER BY last_seen_at DESC LIMIT 200",
                [host_id]
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM alerts ORDER BY last_seen_at DESC LIMIT 200"
            ).fetchall()
    all_alerts = [dict(r) for r in rows]

    if not all_alerts:
        return {"success": True, "data": {"incidents": [], "message": "无告警数据，无法归并"}}

    # 按规则分组
    from collections import defaultdict
    rule_groups = defaultdict(list)
    for a in all_alerts:
        rule_groups[a.get("rule_name", "unknown")].append(a)

    # 攻击链关键词 → 攻击阶段映射
    KILL_CHAIN_MAP = {
        "recon": ["scan", "probe", "recon"],
        "initial_access": ["4625", "brute", "phishing", "exploit"],
        "execution": ["4688", "process_create", "cmd", "powershell"],
        "persistence": ["4698", "7045", "scheduled_task", "service_install", "startup"],
        "credential_access": ["mimikatz", "procdump", "lsass", "sekurlsa"],
        "lateral_movement": ["4672", "4648", "psexec", "wmic", "winrm"],
        "exfiltration": ["5156", "connection_outbound", "c2", "beacon"],
        "defense_evasion": ["1102", "audit_clear", "wevtutil"],
    }

    incidents = []
    processed_ids = set()

    for rule_name, group in rule_groups.items():
        if not group:
            continue
        # 判断攻击阶段
        stage = "general"
        rule_lower = rule_name.lower()
        for s, keywords in KILL_CHAIN_MAP.items():
            if any(kw in rule_lower for kw in keywords):
                stage = s
                break

        first_seen = min(a.get("first_seen_at") or a.get("last_seen_at") or "" for a in group)
        last_seen = max(a.get("last_seen_at") or a.get("first_seen_at") or "" for a in group)
        hosts = list(set(str(a.get("host_id", "")) for a in group if a.get("host_id")))

        title_map = {
            "recon": "侦察扫描",
            "initial_access": "初始入侵",
            "execution": "代码执行",
            "persistence": "持久化驻留",
            "credential_access": "凭据窃取",
            "lateral_movement": "横向移动",
            "exfiltration": "外连C2",
            "defense_evasion": "防御绕过",
            "general": "通用告警",
        }

        alerts_sorted = sorted(group, key=lambda x: x.get("last_seen_at") or "")
        mitre_ids = []
        for a in group:
            if a.get("mitre_attack"):
                mitre_ids.append(a["mitre_attack"])

        incident = {
            "title": f"{title_map.get(stage, '通用告警')}: {rule_name}",
            "description": f"规则 {rule_name} 触发 {len(group)} 次告警。"
                           f"时间窗口: {first_seen} ~ {last_seen}。"
                           f"涉及主机: {', '.join(hosts)}。",
            "severity": group[0].get("severity", "medium"),
            "host_ids": hosts,
            "alert_ids": [a.get("id") for a in group if a.get("id")],
            "kill_chain": stage,
            "mitre_ids": list(set(mitre_ids)),
            "alert_count": len(group),
            "first_seen": first_seen,
            "last_seen": last_seen,
        }
        incidents.append(incident)

    # 存库
    for inc in incidents:
        IncidentCorrelation.create(
            title=inc["title"], description=inc["description"],
            severity=inc["severity"], host_ids=inc["host_ids"],
            alert_ids=inc["alert_ids"], kill_chain=inc["kill_chain"],
            mitre_ids=inc["mitre_ids"],
            recommendations=f"建议排查相关主机 {', '.join(inc['host_ids'])} 的 {inc['kill_chain']} 阶段活动。",
        )

    return {"success": True, "data": {"incidents": incidents, "total": len(incidents)}}


# ─────────────────────────────────────────────
# 2. 自然语言指挥台
# ─────────────────────────────────────────────

@router.post("/ai/query")
def ai_nl_query(
    query: str = Query(""),
    current_user: dict = Depends(get_current_user),
):
    """自然语言 → 结构化查询 + 返回结果."""
    if not query.strip():
        return {"success": True, "data": {
            "intent": "unknown", "params": {}, "summary": "请输入问题",
            "data": None, "suggestions": ["严重的告警", "统计信息", "在线主机", "登录失败的日志", "查看策略"]
        }}
    q = query.lower().strip()

    # 意图识别
    intent = "unknown"
    params = {}

    # 告警查询
    if any(kw in q for kw in ("告警", "alert", "严重", "alerts")):
        intent = "alerts"
        params["limit"] = 20
        if "严重" in q or "critical" in q:
            params["severity"] = "critical"
        if "高危" in q or "high" in q:
            params["severity"] = "high"
        if "未处理" in q or "open" in q or "待处理" in q:
            params["status"] = "open"

    # 日志查询
    elif any(kw in q for kw in ("日志", "log", "登录", "login", "失败")):
        intent = "logs"
        params["page_size"] = 20
        if "登录" in q or "login" in q:
            params["event_type"] = "failed_logon,successful_logon"
        if "失败" in q or "fail" in q:
            params["severity"] = "high"
        if any(kw in q for kw in ("进程", "process", "创建")):
            params["event_type"] = "process_creation"

    # 主机查询
    elif any(kw in q for kw in ("主机", "host", "机器", "服务器", "server")):
        intent = "hosts"
        if "离线" in q or "offline" in q:
            params["status"] = "offline"
        if "在线" in q or "online" in q:
            params["status"] = "online"

    # 案件查询
    elif any(kw in q for kw in ("案件", "case", "事件", "incident")):
        intent = "cases"
        params["limit"] = 20

    # 统计查询
    elif any(kw in q for kw in ("统计", "stats", "汇总", "总数", "分布")):
        intent = "stats"

    # 策略查询
    elif any(kw in q for kw in ("策略", "policy")):
        intent = "policies"

    result = _execute_query(intent, params, q)
    return {"success": True, "data": result}


def _execute_query(intent: str, params: dict, raw_query: str) -> dict:
    """执行查询并返回结果. 使用直接 SQL 兼容已有代码."""
    from app.database import get_connection
    from app.models.policy import DetectionPolicy

    result = {"intent": intent, "params": params, "summary": "", "data": None}

    with get_connection() as conn:
        if intent == "alerts":
            sev = params.get("severity", "")
            status = params.get("status", "")
            limit = params.get("limit", 20)
            conditions = ["1=1"]
            qparams = []
            if sev:
                conditions.append("severity=?")
                qparams.append(sev)
            if status:
                conditions.append("status=?")
                qparams.append(status)
            where = " AND ".join(conditions)
            rows = conn.execute(
                f"SELECT * FROM alerts WHERE {where} ORDER BY last_seen_at DESC LIMIT ?",
                qparams + [limit]
            ).fetchall()
            items = [dict(r) for r in rows]
            result["data"] = items[:10]
            mitre_ids = list(set(r.get("mitre_attack","") for r in items if r.get("mitre_attack")))
            result["summary"] = f"共 {len(items)} 条告警" + (f"，涉及 MITRE: {', '.join(mitre_ids)}" if mitre_ids else "")

        elif intent == "logs":
            event_type = params.get("event_type", "")
            sev = params.get("severity", "")
            limit = params.get("page_size", 20)
            conditions = ["1=1"]
            qparams = []
            if event_type:
                types = event_type.split(",")
                placeholders = ",".join("?" for _ in types)
                conditions.append(f"event_type IN ({placeholders})")
                qparams.extend(types)
            if sev:
                conditions.append("severity=?")
                qparams.append(sev)
            where = " AND ".join(conditions)
            rows = conn.execute(
                f"SELECT * FROM normalized_logs WHERE {where} ORDER BY id DESC LIMIT ?",
                qparams + [limit]
            ).fetchall()
            items = [dict(r) for r in rows]
            result["data"] = items[:10]
            result["summary"] = f"共 {len(items)} 条日志"

        elif intent == "hosts":
            status = params.get("status", "")
            cond = f"WHERE status='{status}'" if status else ""
            rows = conn.execute(f"SELECT id, hostname, ip_address, status FROM hosts {cond} ORDER BY id LIMIT 10").fetchall()
            items = [dict(r) for r in rows]
            result["data"] = items
            result["summary"] = f"共 {len(items)} 台主机" if items else "无匹配主机"

        elif intent == "cases":
            rows = conn.execute(
                "SELECT id, name, status, created_at FROM cases ORDER BY id DESC LIMIT 10"
            ).fetchall()
            items = [dict(r) for r in rows]
            result["data"] = items
            result["summary"] = f"共 {len(items)} 个案件"

        elif intent == "stats":
            total_logs = conn.execute("SELECT COUNT(*) FROM normalized_logs").fetchone()[0]
            total_alerts = conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
            open_alerts = conn.execute("SELECT COUNT(*) FROM alerts WHERE status='open'").fetchone()[0]
            result["data"] = {"total_logs": total_logs, "total_alerts": total_alerts, "open_alerts": open_alerts}
            result["summary"] = f"总日志 {total_logs} 条，总告警 {total_alerts} 条，未处理 {open_alerts} 条"

        elif intent == "policies":
            policies = DetectionPolicy.get_all()
            result["data"] = policies[:5]
            result["summary"] = f"共 {len(policies)} 个策略"

        else:
            result["summary"] = f"未识别查询意图: {raw_query}。支持: 告警/日志/主机/案件/统计/策略"

    return result


# ─────────────────────────────────────────────
# 3. 攻击故事自动讲述
# ─────────────────────────────────────────────

@router.post("/ai/narrate-incident")
def narrate_incident(
    host_id: Optional[int] = Query(None),
    case_id: Optional[int] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """基于时间线+告警生成攻击故事文本."""
    from app.database import get_connection
    alerts = []
    timeline_events = []

    with get_connection() as conn:
        if host_id:
            rows = conn.execute(
                "SELECT * FROM alerts WHERE host_id=? ORDER BY last_seen_at DESC LIMIT 50",
                [host_id]
            ).fetchall()
            alerts = [dict(r) for r in rows]
        if case_id:
            rows = conn.execute(
                "SELECT * FROM timeline_events WHERE case_id=? ORDER BY event_time LIMIT 50",
                [case_id]
            ).fetchall()
            timeline_events = [dict(r) for r in rows]

    if not alerts and not timeline_events:
        return {"success": True, "data": {"story": "暂无数据，无法生成攻击故事"}}

    # 构建故事上下文
    timeline_parts = []
    for a in sorted(alerts, key=lambda x: x.get("last_seen_at") or x.get("first_seen_at") or ""):
        ts = (a.get("last_seen_at") or a.get("first_seen_at") or "")[11:19]
        timeline_parts.append(
            f"{ts} [{a.get('severity','info').upper()}] "
            f"{a.get('event_label') or a.get('rule_name','')} — {a.get('title','')[:60]}"
        )

    if timeline_events:
        # 从分析结果获取MITRE信息
        pass

    story_lines = ["# 攻击时间线", ""]
    if timeline_parts:
        attack_stages = []
        current_stage = ""
        for line in timeline_parts:
            # 检测阶段切换
            if "AUDIT" in line or "1102" in line:
                current_stage = "## 🚨 阶段: 防御绕过/清理痕迹"
            elif "EXECUT" in line or "process" in line or "4688" in line:
                current_stage = "## ⚡ 阶段: 代码执行"
            elif "LOGON" in line or "4625" in line or "SUCCESS" in line:
                current_stage = "## 🔑 阶段: 初始访问"
            elif "CONNEC" in line or "5156" in line or "外连" in line:
                current_stage = "## 🌐 阶段: C2通信/外连"
            elif "SERVICE" in line or "TASK" in line or "4698" in line or "7045" in line:
                current_stage = "## 📦 阶段: 持久化驻留"

            if current_stage and current_stage not in attack_stages:
                attack_stages.append(current_stage)
                story_lines.append(current_stage)
            story_lines.append(f"- {line}")

        story_lines.extend(["", "## 📋 总结", f"共发现 {len(alerts)} 条相关告警，涉及 {len(attack_stages)} 个攻击阶段。"])

        if any("1102" in l for l in timeline_parts):
            story_lines.append("⚠️ **发现审计日志清除事件 (Event 1102)**，强烈建议立即隔离受感染主机。")

        story_lines.extend(["", "## 💡 建议措施", "- 隔离告警来源主机", "- 检查同网段其他主机", "- 确认攻击入口和清理持久化机制", "- 生成复盘报告"])
    else:
        story_lines.append("无时间线数据可生成故事。")

    story = "\n".join(story_lines)
    return {"success": True, "data": {"story": story, "alert_count": len(alerts)}}


# ─────────────────────────────────────────────
# 4. 误报自学习
# ─────────────────────────────────────────────

@router.post("/ai/false-positive")
def mark_false_positive(
    alert_id: int = Query(...),
    reason: str = Query(""),
    current_user: dict = Depends(get_current_user),
):
    """标记告警为误报并自动学习模式."""
    from app.models.false_positive import FalsePositivePattern
    from app.database import get_connection

    with get_connection() as conn:
        row = conn.execute("SELECT * FROM alerts WHERE id=?", [alert_id]).fetchone()
        if not row:
            raise HTTPException(404, "告警不存在")
        alert = dict(row)

        # 标记为 dismissed
        conn.execute(
            "UPDATE alerts SET status='dismissed', dismissed_reason=? WHERE id=?",
            [reason, alert_id]
        )
        conn.commit()

    # 自动学习模式
    source_proc = alert.get("source_process", "") or ""
    rule_name = alert.get("rule_name", "") or ""
    host_id = alert.get("host_id", 0) or 0

    if rule_name:
        FalsePositivePattern.create(
            rule_name=rule_name,
            source_process=source_proc,
            host_id=host_id,
            reason=reason or "用户标记误报",
            created_by=current_user.get("username", "system"),
        )

    return {"success": True, "data": {"message": "已标记为误报，模式已学习"}}


@router.get("/ai/false-positives")
def list_false_positives(
    page: int = Query(1, ge=1),
    page_size: int = Query(50),
    current_user: dict = Depends(get_current_user),
):
    from app.models.false_positive import FalsePositivePattern
    return {"success": True, "data": FalsePositivePattern.list(page=page, page_size=page_size)}


@router.delete("/ai/false-positives/{pattern_id}")
def delete_false_positive(pattern_id: int, current_user: dict = Depends(get_current_user)):
    from app.models.false_positive import FalsePositivePattern
    ok = FalsePositivePattern.delete(pattern_id)
    return {"success": ok}


# ─────────────────────────────────────────────
# 5. 预测性沦陷预警
# ─────────────────────────────────────────────

@router.get("/ai/risk-ranking")
def risk_ranking(current_user: dict = Depends(get_current_user)):
    """主机沦陷风险评分排行榜."""
    from app.database import get_connection

    with get_connection() as conn:
        hosts = conn.execute("SELECT id, hostname, ip_address, status FROM hosts ORDER BY id").fetchall()

    rankings = []
    for h in hosts:
        host_id = h["id"]
        score = _calculate_risk_score(host_id)
        if score > 0:
            rankings.append({
                "host_id": host_id,
                "hostname": h["hostname"],
                "ip": h["ip_address"] or "",
                "status": h["status"],
                "risk_score": score,
                "risk_level": "critical" if score >= 70 else ("high" if score >= 40 else ("medium" if score >= 20 else "low")),
            })

    rankings.sort(key=lambda x: x["risk_score"], reverse=True)
    return {"success": True, "data": {"rankings": rankings[:20], "total": len(rankings)}}


def _calculate_risk_score(host_id: int) -> int:
    """轻量加权风险评分."""
    score = 0
    try:
        from app.database import get_connection
        with get_connection() as conn:
            # 1. 登录失败暴增 (最高25分)
            failed = conn.execute(
                "SELECT COUNT(*) FROM alerts WHERE host_id=? AND severity='high' AND rule_name LIKE '%fail%logon%'",
                [host_id]
            ).fetchone()[0]
            score += min(failed * 5, 25)

            # 2. 严重告警 (每个15分，最高30分)
            critical = conn.execute(
                "SELECT COUNT(*) FROM alerts WHERE host_id=? AND severity='critical' AND status='open'",
                [host_id]
            ).fetchone()[0]
            score += min(critical * 15, 30)

            # 3. 审计日志清除 (30分，铁证)
            cleared = conn.execute(
                "SELECT COUNT(*) FROM alerts WHERE host_id=? AND rule_name LIKE '%audit%' AND severity='critical'",
                [host_id]
            ).fetchone()[0]
            score += min(cleared * 30, 30)

            # 4. 异常外连 (每个10分)
            conn_out = conn.execute(
                "SELECT COUNT(*) FROM alerts WHERE host_id=? AND rule_name LIKE '%connection%'",
                [host_id]
            ).fetchone()[0]
            score += min(conn_out * 10, 20)

            # 5. 持久化活动 (每个10分)
            persist = conn.execute(
                "SELECT COUNT(*) FROM alerts WHERE host_id=? AND (rule_name LIKE '%service%' OR rule_name LIKE '%task%' OR rule_name LIKE '%persistence%')",
                [host_id]
            ).fetchone()[0]
            score += min(persist * 10, 20)

            # 6. 离线时长 (最多15分)
            status_row = conn.execute(
                "SELECT status FROM hosts WHERE id=?", [host_id]
            ).fetchone()
            if status_row and status_row["status"] != "online":
                score += 10

            # 7. PS编码执行 (每个10分)
            ps_encoded = conn.execute(
                "SELECT COUNT(*) FROM alerts WHERE host_id=? AND (title LIKE '%powershell%' OR title LIKE '%PS%' OR rule_name LIKE '%powershell%')",
                [host_id]
            ).fetchone()[0]
            score += min(ps_encoded * 10, 15)

    except Exception as e:
        logger.debug("Risk score calc failed for host %d: %s", host_id, e)

    return min(score, 100)
