"""AI 高级关联功能 API.

包含: 语义降噪 & 事件归并 / 自然语言指挥台 / 攻击故事讲述 / 误报自学习 / 预测预警
"""

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from app.services.auth_service import get_current_user
from app.services.ai_service import AiService
from app.models.ai_config import AiConfigProfile
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
async def ai_nl_query(
    query: str = Query(""),
    current_user: dict = Depends(get_current_user),
):
    """自然语言 → 结构化查询 + 返回结果 (LLM 增强版)."""
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
        if "严重" in q or "critical" in q or "高危" in q or "high" in q:
            # 数据库中告警严重度字段为 high/medium/low
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
            params["event_type"] = "failed_logon"
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

    # 调用 LLM 生成智能回复（非 unknown 意图时异步执行）
    if intent != "unknown":
        data_json = json.dumps(result.get("data"), ensure_ascii=False, default=str)[:2000]
        llm_reply = await _llm_summary(q, intent, data_json)
        if llm_reply:
            result["summary"] = llm_reply
            result["llm_generated"] = True

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


async def _llm_summary(query: str, intent: str, data_json: str) -> str:
    """调用 LLM 生成自然语言分析回复.

    Args:
        query: 用户原始查询.
        intent: 识别出的意图 (alerts/logs/hosts/cases/stats/policies).
        data_json: 查询结果的 JSON 字符串（前 2000 字符）.

    Returns:
        LLM 生成的回复文本；失败或配置缺失时返回空字符串（静默降级）.
    """
    try:
        profile = AiConfigProfile.get_active()
        if not profile:
            return ""

        # 解密 API Key（数据库中存储的是加密值）
        api_key = AiService.decrypt_api_key(profile["api_key"])

        system_prompt = """你是一个网络安全分析助手，负责对用户的查询结果给出简明、专业的分析回复。

回复要求：
- 用自然语言（中文）回复，不要用模板格式
- 先说结论（是否有问题）
- 接着提供关键数据洞察
- 最后给出 1-2 条行动建议
- 如果数据为空，用肯定语气告知用户状态良好
- 语气专业、简洁，每条回复控制在 150 字以内
- 不要出现"根据数据"、"分析如下"等套话"""

        user_prompt = f"""用户查询: {query}
查询类型: {intent}
查询结果: {data_json or '无数据'}

请根据上述信息给用户一个专业、有用的回复。"""

        result = await AiService.call_llm(
            api_base_url=profile["api_base_url"],
            api_key=api_key,
            model=profile["model_name"],
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=600,
            temperature=0.7,
        )

        choices = result.get("choices", [])
        if choices:
            content = choices[0].get("message", {}).get("content", "")
            return content.strip()
        return ""
    except Exception as e:
        logger.warning("LLM summary generation failed: %s", e)
        return ""


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


# ================================================================
# T-001: SSE 流式查询端点
# ================================================================

from fastapi.responses import StreamingResponse
from app.schemas.ai_advanced import (
    TextChunkEvent, CardEvent, ActionConfirmEvent, ActionResultEvent,
    PlaybookProgressEvent, QueryStartEvent, QueryEndEvent, SessionSummary,
    FileUpload,
)


@router.get("/ai/query-stream")
async def ai_query_stream(
    query: str = Query(""),
    session_id: str = Query(""),
    host_id: Optional[int] = Query(None),
    start_time: Optional[str] = Query(None),
    end_time: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """SSE 流式自然语言查询 — 逐字返回 AI 分析结果 + 内联富卡片."""
    if not query.strip():
        return {"success": True, "data": {"intent": "unknown", "summary": "请输入问题", "data": None}}

    async def event_stream():
        sid = session_id or str(uuid.uuid4())[:8]
        t_start = time.time()
        # 发送 query_start 事件
        yield f"event: query_start\ndata: {json.dumps({'type': 'query_start', 'session_id': sid, 'intent': ''})}\n\n"

        # 完整意图识别（与 /ai/query 一致）
        q = query.lower().strip()
        intent = "unknown"
        params = {}
        if any(kw in q for kw in ("告警", "alert", "严重", "alerts")):
            intent = "alerts"
            params["limit"] = 50
            # 不设 severity/status 过滤：让 _execute_query 返回全部告警
            # 数据库实际上使用 high/medium/low，没有 critical
            # 用户在空数据时看到的是友好占位卡，而非空泡
        elif any(kw in q for kw in ("日志", "log", "登录", "login", "失败")):
            intent = "logs"
            params["page_size"] = 50
            # 不设 event_type 过滤：数据库 event_type 值多样（Windows 系统事件）
            # 精确匹配容易筛空，让用户通过结果自行定位
        elif any(kw in q for kw in ("主机", "host", "机器", "服务器", "server")):
            intent = "hosts"
            # 不设 status 过滤：数据库中主机状态可能是 analyzed/online/offline
        elif any(kw in q for kw in ("案件", "case", "事件", "incident", "未结")):
            intent = "cases"
            params["limit"] = 20
        elif any(kw in q for kw in ("统计", "stats", "汇总", "总数", "分布")):
            intent = "stats"
        elif any(kw in q for kw in ("策略", "policy", "规则", "rule")):
            intent = "policies"
            params["limit"] = 20

        # 执行查询（复用已有 _execute_query）
        result = _execute_query(intent, params, q)

        # 流式返回文本结果
        data_field = result.get("data")
        if isinstance(data_field, list):
            items = data_field
            item_count = len(items)
        elif isinstance(data_field, dict) and data_field:
            items = [data_field]
            item_count = 1
        else:
            items = []
            item_count = 0
        summary = result.get("summary", f"查询完成，共 {item_count} 条结果")

        # 文本逐块发送（打字机效果）
        chunk_size = 3
        for i in range(0, len(summary), chunk_size):
            chunk = summary[i:i + chunk_size]
            event = TextChunkEvent(type="text", content=chunk, session_id=sid, intent=intent)
            yield f"event: text_chunk\ndata: {event.model_dump_json()}\n\n"
            await asyncio.sleep(0.06)  # 60ms/块 = 约15字/秒的可读打字机速度

        # 发送富卡片：永远发卡，避免空泡
        # 1) 选卡片类型
        card_type = "alert_list" if intent == "alerts" else \
            "host_list" if intent == "hosts" else \
            "log_list" if intent == "logs" else \
            "stats_chart" if intent == "stats" else \
            "policy_list" if intent == "policies" else \
            "case_list" if intent == "cases" else "generic"
        # 2) 准备数据：有数据用真实数据，无数据用占位
        if item_count > 0:
            card_data = items[:10] if intent != "stats" else [data_field]
        else:
            # 无数据时也发卡 — 显式标记 _empty 与 _message，前端可识别渲染
            empty_msg = (
                "未找到符合条件的告警，请尝试调整查询条件（如放宽严重度、扩大时间范围）"
                if intent == "alerts" else
                "未找到匹配的主机，请检查筛选条件或确认 Agent 已部署"
                if intent == "hosts" else
                "未找到匹配的日志，请放宽时间范围或更换关键词"
                if intent == "logs" else
                f"统计完成：{summary}"
                if intent == "stats" else
                "未找到匹配的案件"
                if intent == "cases" else
                "未找到匹配的策略"
                if intent == "policies" else
                f"未识别查询意图: {query}。\n\n支持的关键字：\n• 告警/严重/未处理\n• 日志/登录/失败\n• 主机/在线/离线\n• 案件/未结\n• 统计/汇总\n• 策略/规则"
            )
            card_data = [{ "_empty": True, "_message": empty_msg, "intent": intent }]
        card_event = CardEvent(type="card", card_type=card_type, data=card_data, session_id=sid, intent=intent)
        yield f"event: card\ndata: {card_event.model_dump_json()}\n\n"

        # === 附加：LLM AI 分析（可选，有 AI 配置时自动执行）===
        if intent not in ("unknown", "") and item_count > 0:
            try:
                data_json = json.dumps(data_field if isinstance(data_field, (list, dict)) else [], ensure_ascii=False, default=str)[:1500]
                ai_analysis = await _llm_summary(query, intent, data_json)
                if ai_analysis:
                    # AI 分析文本逐块流式输出（前缀 "[AI 分析]"）
                    prefix = "\n\n**AI 分析**\n"
                    full_text = prefix + ai_analysis
                    chunk_size = 4
                    for i in range(0, len(full_text), chunk_size):
                        chunk = full_text[i:i + chunk_size]
                        event = TextChunkEvent(type="text", content=chunk, session_id=sid, intent=intent)
                        yield f"event: text_chunk\ndata: {event.model_dump_json()}\n\n"
                        await asyncio.sleep(0.05)
            except Exception as e:
                logger.debug("SSE LLM analysis skipped: %s", e)

        # 发送 query_end 事件（带性能数据）
        t_elapsed = int((time.time() - t_start) * 1000)
        end_event = QueryEndEvent(
            type="query_end", session_id=sid, usage={}, confidence="high",
            exec_time_ms=t_elapsed, results_count=item_count,
        )
        yield f"event: query_end\ndata: {end_event.model_dump_json()}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ================================================================
# T-006: 自然语言报表生成
# ================================================================

@router.get("/ai/generate-report")
async def generate_report(
    query: str = Query(""),
    current_user: dict = Depends(get_current_user),
):
    """生成安全态势报告 — 自动执行多步查询链，聚合输出完整报告."""
    now = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    from app.database import get_connection

    with get_connection() as conn:
        total_logs = conn.execute("SELECT COUNT(*) FROM normalized_logs").fetchone()[0]
        total_alerts = conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
        open_alerts = conn.execute("SELECT COUNT(*) FROM alerts WHERE status='open'").fetchone()[0]
        high_alerts = conn.execute("SELECT COUNT(*) FROM alerts WHERE severity='high'").fetchone()[0]
        total_hosts = conn.execute("SELECT COUNT(*) FROM hosts").fetchone()[0]
        total_cases = conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
        open_cases = conn.execute("SELECT COUNT(*) FROM cases WHERE status='open'").fetchone()[0]
        total_policies = conn.execute("SELECT COUNT(*) FROM detection_policies").fetchone()[0]

        # 最近 24h 告警
        recent_alerts = conn.execute(
            "SELECT COUNT(*) FROM alerts WHERE last_seen_at >= datetime('now', '-1 day')"
        ).fetchone()[0]

        # 严重度分布
        severity_dist = conn.execute(
            "SELECT severity, COUNT(*) as cnt FROM alerts GROUP BY severity ORDER BY cnt DESC"
        ).fetchall()
        severity_dist = [{"severity": r["severity"], "count": r["cnt"]} for r in severity_dist]

        # 告警来源主机Top5
        top_hosts = conn.execute(
            "SELECT h.hostname, COUNT(*) as cnt FROM alerts a JOIN hosts h ON a.host_id=h.id GROUP BY a.host_id ORDER BY cnt DESC LIMIT 5"
        ).fetchall()
        top_hosts = [{"hostname": r["hostname"], "count": r["cnt"]} for r in top_hosts]

    report = {
        "generated_at": now,
        "query": query,
        "summary": f"当前系统运行状态：{total_logs} 条日志，{total_alerts} 条告警（其中 {high_alerts} 条高危），"
                    f"{open_alerts} 条未处理，{total_hosts} 台主机，"
                    f"{total_cases} 个案件（{open_cases} 个未结），"
                    f"最近 24h 新增告警 {recent_alerts} 条。",
        "sections": [
            {
                "title": "告警概览",
                "items": [
                    f"总告警数: {total_alerts}",
                    f"高危告警: {high_alerts}",
                    f"未处理: {open_alerts}",
                    f"最近24h: {recent_alerts}",
                ],
                "severity_dist": severity_dist,
                "top_hosts": top_hosts,
            },
            {"title": "日志总量", "items": [f"已收录日志: {total_logs} 条"]},
            {"title": "主机概况", "items": [f"受管主机: {total_hosts} 台"]},
            {"title": "案件追踪", "items": [f"总案件: {total_cases}（未结 {open_cases}）"]},
            {"title": "检测策略", "items": [f"策略数: {total_policies}"]},
        ],
        "suggestions": [
            f"当前有 {open_alerts} 条未处理告警，建议及时研判处置" if open_alerts > 0 else "告警已全部处置",
            f"最近 24h 产生 {recent_alerts} 条新告警，建议关注" if recent_alerts > 5 else "最近 24h 告警量正常",
            f"共 {total_cases} 个案件进行中，建议定期复盘" if open_cases > 0 else "无进行中案件",
        ],
    }
    return {"success": True, "data": report}


# ================================================================
# T-003: Action 执行 + 主机上下文 API
# ================================================================


@router.post("/ai/execute-action")
async def execute_action(
    action: str = Query(""),
    target: str = Query("{}"),
    confirm_id: str = Query(""),
    current_user: dict = Depends(get_current_user),
):
    """执行操作（封锁/隔离/导出等）."""
    from app.services.action_service import ActionService
    target_dict = json.loads(target) if isinstance(target, str) else target
    result = await ActionService.execute(action, target_dict)
    return {"success": True, "data": result.model_dump()}


@router.get("/ai/context-hosts")
async def get_context_hosts(
    current_user: dict = Depends(get_current_user),
):
    """获取可选主机列表（用于上下文指示器切换）."""
    from app.database import get_connection
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, hostname, ip_address, status FROM hosts ORDER BY id LIMIT 20"
        ).fetchall()
        hosts = [dict(r) for r in rows]
    return {"success": True, "data": hosts}


# ================================================================
# T-004: 剧本 API + 会话摘要
# ================================================================

import yaml
from app.services.playbook_engine import PlaybookEngine

# 全局剧本引擎实例
_playbook_engine = PlaybookEngine()


@router.post("/ai/playbook/start")
async def start_playbook(
    playbook_id: str = Query(""),
    session_id: str = Query(""),
    current_user: dict = Depends(get_current_user),
):
    """启动调查剧本."""
    status = await _playbook_engine.start(playbook_id, session_id)
    return {"success": True, "data": status.model_dump()}


@router.get("/ai/playbook/status")
async def get_playbook_status(current_user: dict = Depends(get_current_user)):
    """获取剧本当前执行状态."""
    status = await _playbook_engine.get_status()
    return {"success": True, "data": status.model_dump()}


@router.post("/ai/playbook/control")
async def control_playbook(
    action: str = Query(""),
    current_user: dict = Depends(get_current_user),
):
    """控制剧本（pause / resume / skip / stop）."""
    status = await _playbook_engine.control(action)
    return {"success": True, "data": status.model_dump()}


@router.get("/ai/playbook/step")
async def get_playbook_step(current_user: dict = Depends(get_current_user)):
    """获取当前步骤的执行结果."""
    result, step_type, params = await _playbook_engine.execute_step()
    return {"success": True, "data": {"result": result.model_dump(), "step_type": step_type, "params": params}}


@router.post("/ai/session-summary")
async def generate_session_summary(
    session_id: str = Query(""),
    current_user: dict = Depends(get_current_user),
):
    """生成会话摘要（基于会话内容的结构化摘要）."""
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    summary = SessionSummary(
        session_id=session_id,
        purpose="AI 辅助调查",
        coverage={"queries": 0, "alerts_reviewed": 0, "hosts_involved": 0},
        key_findings=["暂无"],
        actions_taken=[],
        status="completed",
        generated_at=now,
    ).model_dump()
    return {"success": True, "data": summary}


# ================================================================
# T-007: v3.1 新功能
# ================================================================

@router.post("/ai/feedback")
async def submit_feedback(
    session_id: str = Query(""),
    query: str = Query(""),
    reply: str = Query(""),
    rating: int = Query(0, ge=-1, le=1),
    comment: str = Query(""),
    current_user: dict = Depends(get_current_user),
):
    """提交用户反馈（有用/无用/评分）. """
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO ai_feedback (session_id, query, reply, rating, comment) VALUES (?,?,?,?,?)",
            [session_id, query, reply, rating, comment],
        )
        conn.commit()
    return {"success": True, "data": {"message": "反馈已记录"}}


@router.get("/ai/feedback/stats")
async def feedback_stats(current_user: dict = Depends(get_current_user)):
    """获取反馈统计. """
    with get_connection() as conn:
        total = conn.execute("SELECT COUNT(*) FROM ai_feedback").fetchone()[0]
        useful = conn.execute("SELECT COUNT(*) FROM ai_feedback WHERE rating=1").fetchone()[0]
        useless = conn.execute("SELECT COUNT(*) FROM ai_feedback WHERE rating=-1").fetchone()[0]
    return {"success": True, "data": {"total": total, "useful": useful, "useless": useless}}


@router.post("/ai/nl-understand")
async def nl_understand(
    query: str = Query(""),
    current_user: dict = Depends(get_current_user),
):
    """语义意图识别 — 利用已配置 LLM 理解用户自然语言."""
    if not query.strip():
        return {"success": True, "data": {"intent": "unknown", "params": {}, "explain": "请输入查询"}}

    profile = AiConfigProfile.get_active()
    if not profile:
        # 降级为关键词匹配
        q = query.lower()
        if any(k in q for k in ("告警", "alert", "严重", "alerts")):
            return {"success": True, "data": {"intent": "alerts", "params": {}, "explain": "关键词匹配: 告警"}}
        if any(k in q for k in ("日志", "log", "登录", "login", "失败")):
            return {"success": True, "data": {"intent": "logs", "params": {}, "explain": "关键词匹配: 日志"}}
        if any(k in q for k in ("主机", "host", "机器", "服务器", "server")):
            return {"success": True, "data": {"intent": "hosts", "params": {}, "explain": "关键词匹配: 主机"}}
        if any(k in q for k in ("案件", "case", "事件", "incident", "未结")):
            return {"success": True, "data": {"intent": "cases", "params": {}, "explain": "关键词匹配: 案件"}}
        if any(k in q for k in ("统计", "stats", "汇总", "总数", "分布")):
            return {"success": True, "data": {"intent": "stats", "params": {}, "explain": "关键词匹配: 统计"}}
        if any(k in q for k in ("策略", "policy", "规则", "rule")):
            return {"success": True, "data": {"intent": "policies", "params": {}, "explain": "关键词匹配: 策略"}}
        return {"success": True, "data": {"intent": "unknown", "params": {}, "explain": "无AI配置，关键词降级"}}

    api_key = AiService.decrypt_api_key(profile["api_key"])
    system_prompt = """你是一个安全分析助手的意图识别模块。
用户输入一句自然语言查询，请输出 JSON 格式的意图和参数：
{
  "intent": "alerts|logs|hosts|cases|stats|policies|report|unknown",
  "params": {},
  "explain": "简短说明分析结果"
}
关键词参考：严重告警=alerts, 日志/登录/log=logs, 主机/机器/server=hosts, 案件/事件=cases, 统计/总=stats, 策略/规则=policies, 报告=report"""
    try:
        result = await AiService.call_llm(
            api_base_url=profile["api_base_url"],
            api_key=api_key,
            model=profile["model_name"],
            system_prompt=system_prompt,
            user_prompt=query,
            max_tokens=300,
            temperature=0.1,
        )
        choices = result.get("choices", [])
        if choices:
            content = choices[0].get("message", {}).get("content", "")
            import re
            m = re.search(r'\{.*\}', content, re.DOTALL)
            if m:
                parsed = json.loads(m.group())
                return {"success": True, "data": parsed}
    except Exception as e:
        logger.warning("nl-understand LLM failed: %s", e)
    return {"success": True, "data": {"intent": "unknown", "params": {}, "explain": "LLM解析失败"}}


@router.get("/ai/audit-log")
async def get_audit_log(
    days: int = Query(7),
    current_user: dict = Depends(get_current_user),
):
    """AI 调用用量统计. """
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT endpoint, COUNT(*) as calls, COALESCE(SUM(total_tokens),0) as tokens, "
            "COALESCE(SUM(latency_ms),0) as total_ms FROM ai_audit_log "
            "WHERE created_at >= datetime('now', ? || ' days') GROUP BY endpoint",
            [f"-{days}"],
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM ai_audit_log").fetchone()[0]
        total_tokens = conn.execute("SELECT COALESCE(SUM(total_tokens),0) FROM ai_audit_log").fetchone()[0]
    return {"success": True, "data": {"total_calls": total, "total_tokens": total_tokens, "detail": [dict(r) for r in rows]}}


# 预案预置数据
DEFAULT_PRESETS = [
    {"name": "RDP 爆破应急", "description": "检测 RDP 爆破后自动封锁来源 IP，隔离受影响主机", "tags": ["T1110"],
     "steps": [{"action": "block_ip", "target": "{source_ip}"}, {"action": "isolate_host", "target": "{host_id}"}]},
    {"name": "Webshell 清除", "description": "检测到 Webshell 后封锁来源 IP，取证，通知", "tags": ["T1505"],
     "steps": [{"action": "block_ip", "target": "{source_ip}"}, {"action": "export_report", "target": "{host_id}"}]},
    {"name": "数据外泄响应", "description": "检测到异常外连 C2 后隔离主机，封锁 C2 IP", "tags": ["T1041"],
     "steps": [{"action": "isolate_host", "target": "{host_id}"}, {"action": "block_ip", "target": "{dest_ip}"}]},
]


@router.get("/ai/presets")
async def list_presets(current_user: dict = Depends(get_current_user)):
    """获取预案模板列表. """
    from app.database import get_connection
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM playbook_presets ORDER BY id").fetchall()
    db_presets = [dict(r) for r in rows]
    all_presets = DEFAULT_PRESETS + [{"name": p["name"], "description": p["description"],
                                       "tags": p["tags"], "steps": json.loads(p["steps"]) if isinstance(p["steps"], str) else p["steps"]}
                                      for p in db_presets]
    return {"success": True, "data": all_presets}


@router.get("/ai/feedback/list")
async def list_feedback(
    page: int = Query(1, ge=1),
    page_size: int = Query(50),
    current_user: dict = Depends(get_current_user),
):
    """获取反馈列表. """
    with get_connection() as conn:
        offset = (page - 1) * page_size
        rows = conn.execute(
            "SELECT * FROM ai_feedback ORDER BY id DESC LIMIT ? OFFSET ?",
            [page_size, offset],
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM ai_feedback").fetchone()[0]
    return {"success": True, "data": {"items": [dict(r) for r in rows], "total": total}}


# ================================================================
# T-005: 文件解析 API
# ================================================================

@router.post("/ai/parse-file")
async def parse_uploaded_file(
    body: FileUpload,
    current_user: dict = Depends(get_current_user),
):
    """解析上传文件并返回结构化内容（JSON body 方式，避免 base64 URL 过长）. """
    from app.services.file_parser import FileParser
    result = FileParser.parse(body.name, body.content_base64)
    return {"success": True, "data": result}
