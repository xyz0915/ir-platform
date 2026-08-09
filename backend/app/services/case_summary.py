"""案件详情聚合服务 — 一次性返回案件研判所需的核心态势数据.

应急专家视角：案件详情必须一眼回答
  1. 这事多严重？（derived_severity）
  2. 发生了什么？（alert_stats / top_alerts）
  3. 影响了哪些资产？（host_stats / ioc_summary / ttp_summary）
  4. 处置到哪一步了？（remediation_progress / triage_progress）
  5. 时间线怎么走的？（timeline）

设计目标：前端一次请求即可得到全部卡片数据，避免 N 次往返。
所有查询在单个 DB 连接内完成，保证一致性与性能。
"""

import json
import logging
from typing import Any, Dict, List, Optional

from app.database import get_connection
from app.models.security_event import ATTACK_STAGE_LABELS
from app.models.threat_intel import ThreatIntel

logger = logging.getLogger(__name__)

SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0, "none": 0}
SEVERITY_ORDER = ["critical", "high", "medium", "low"]
ALERT_STATUS_ORDER = ["open", "acknowledged", "resolved", "dismissed"]


def _safe_json(value: Any) -> Any:
    if isinstance(value, str) and value:
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return None
    return value


def get_case_summary(case_id: int) -> Dict[str, Any]:
    """聚合案件详情态势数据.

    Returns:
        包含 case / alert_stats / top_alerts / host_stats / timeline /
        remediation_progress / triage_progress / ioc_summary / ttp_summary /
        ai_summary 的字典。
    """
    with get_connection() as conn:
        case = conn.execute(
            "SELECT * FROM cases WHERE id = ?", (case_id,)
        ).fetchone()
        if not case:
            return {}

        case = dict(case)
        host_ids = _case_host_ids(conn, case_id)

        # 1) 派生严重度（取关联告警最高严重度，忽略已Dismiss）
        derived_severity = _derived_severity(conn, host_ids)

        # 2) 告警态势
        alert_stats, top_alerts = _alert_section(conn, host_ids)

        # 3) 主机态势
        host_stats = _host_section(conn, case_id, host_ids)

        # 4) 处置闭环进度
        remediation_progress = _remediation_section(conn, case_id)

        # 5) 取证任务进度
        triage_progress = _triage_section(conn, host_ids)

        # 6) IOC 与威胁情报
        ioc_summary, intel_by_ioc = _ioc_section(conn, host_ids)

        # 7) 攻击链 / TTP
        ttp_summary = _ttp_section(conn, host_ids, intel_by_ioc)

        # 8) AI 分析结论
        ai_summary = _ai_section(conn, host_ids)

        # 9) 响应时间线（案件级里程碑）
        timeline = _timeline(conn, case, host_ids)

    return {
        "case": {
            "id": case.get("id"),
            "name": case.get("name"),
            "case_number": case.get("case_number"),
            "status": case.get("status"),
            "priority": case.get("priority"),
            "created_at": case.get("created_at"),
            "updated_at": case.get("updated_at"),
            "description": case.get("description"),
            "host_count": case.get("host_count", 0),
            "log_count": case.get("log_count", 0),
            "derived_severity": derived_severity,
        },
        "alert_stats": alert_stats,
        "top_alerts": top_alerts,
        "host_stats": host_stats,
        "timeline": timeline,
        "remediation_progress": remediation_progress,
        "triage_progress": triage_progress,
        "ioc_summary": ioc_summary,
        "ttp_summary": ttp_summary,
        "ai_summary": ai_summary,
    }


# ────────────────────────────────────────────────────────────
# 内部聚合函数
# ────────────────────────────────────────────────────────────

def _case_host_ids(conn, case_id: int) -> List[int]:
    rows = conn.execute(
        "SELECT id FROM hosts WHERE case_id = ?", (case_id,)
    ).fetchall()
    return [r["id"] for r in rows]


def _in_clause(ids: List[int]) -> str:
    return ",".join("?" * len(ids)) if ids else "NULL"


def _derived_severity(conn, host_ids: List[int]) -> str:
    if not host_ids:
        return "none"
    rows = conn.execute(
        f"""SELECT severity FROM alerts
            WHERE host_id IN ({_in_clause(host_ids)}) AND status != 'dismissed'""",
        host_ids,
    ).fetchall()
    max_rank = 0
    for r in rows:
        max_rank = max(max_rank, SEVERITY_RANK.get(r["severity"], 0))
    if max_rank == 0:
        return "none"
    return next(k for k, v in SEVERITY_RANK.items() if v == max_rank)


def _alert_section(conn, host_ids: List[int]):
    if not host_ids:
        return (
            {"total": 0, "by_severity": {}, "by_status": {}},
            [],
        )
    placeholder = _in_clause(host_ids)
    total = conn.execute(
        f"SELECT COUNT(*) c FROM alerts WHERE host_id IN ({placeholder})",
        host_ids,
    ).fetchone()["c"]

    by_severity: Dict[str, int] = {}
    sev_rows = conn.execute(
        f"SELECT severity, COUNT(*) c FROM alerts WHERE host_id IN ({placeholder}) GROUP BY severity",
        host_ids,
    ).fetchall()
    for r in sev_rows:
        by_severity[r["severity"]] = r["c"]

    by_status: Dict[str, int] = {}
    st_rows = conn.execute(
        f"SELECT status, COUNT(*) c FROM alerts WHERE host_id IN ({placeholder}) GROUP BY status",
        host_ids,
    ).fetchall()
    for r in st_rows:
        by_status[r["status"]] = r["c"]

    # Top 告警：按严重度 + count 排序取前 8
    alert_rows = conn.execute(
        f"""SELECT id, host_id, rule_label, rule_name, title, severity, status,
                   source_process, source_ip, count, first_seen_at, last_seen_at
            FROM alerts WHERE host_id IN ({placeholder})
            ORDER BY count DESC, first_seen_at DESC LIMIT 50""",
        host_ids,
    ).fetchall()
    ranked = sorted(
        alert_rows,
        key=lambda a: (SEVERITY_RANK.get(a["severity"], 0), a["count"]),
        reverse=True,
    )[:8]
    top_alerts = [
        {
            "id": a["id"],
            "host_id": a["host_id"],
            "rule_label": a["rule_label"] or a["rule_name"] or a["title"],
            "severity": a["severity"],
            "status": a["status"],
            "source_process": a["source_process"],
            "source_ip": a["source_ip"],
            "count": a["count"],
            "first_seen_at": a["first_seen_at"],
            "last_seen_at": a["last_seen_at"],
        }
        for a in ranked
    ]
    return (
        {"total": total, "by_severity": by_severity, "by_status": by_status},
        top_alerts,
    )


def _host_section(conn, case_id: int, host_ids: List[int]):
    total = conn.execute(
        "SELECT COUNT(*) c FROM hosts WHERE case_id = ?", (case_id,)
    ).fetchone()["c"]

    by_status: Dict[str, int] = {}
    st_rows = conn.execute(
        "SELECT status, COUNT(*) c FROM hosts WHERE case_id = ? GROUP BY status",
        (case_id,),
    ).fetchall()
    for r in st_rows:
        by_status[r["status"]] = r["c"]

    online = 0
    if host_ids:
        online = conn.execute(
            f"""SELECT COUNT(DISTINCT a.id) c FROM agents a
                JOIN hosts h ON a.host_id = h.id
                WHERE h.case_id = ? AND a.status = 'online'""",
            (case_id,),
        ).fetchone()["c"]

    # 风险 Top 主机：以 IOC 命中数作为风险代理指标
    risk_top: List[Dict[str, Any]] = []
    if host_ids:
        placeholder = _in_clause(host_ids)
        risk_rows = conn.execute(
            f"""SELECT h.id, h.hostname, h.ip_address, COUNT(ih.id) AS ioc_hits
                FROM hosts h LEFT JOIN ioc_hits ih ON ih.host_id = h.id
                WHERE h.case_id = ?
                GROUP BY h.id ORDER BY ioc_hits DESC LIMIT 5""",
            (case_id,),
        ).fetchall()
        risk_top = [
            {
                "host_id": r["id"],
                "hostname": r["hostname"],
                "ip_address": r["ip_address"],
                "risk_score": r["ioc_hits"],
            }
            for r in risk_rows
        ]

    return {
        "total": total,
        "by_status": by_status,
        "online_agents": online,
        "risk_top": risk_top,
    }


def _remediation_section(conn, case_id: int) -> Dict[str, Any]:
    rows = conn.execute(
        "SELECT items FROM remediation_checklist WHERE case_id = ?", (case_id,)
    ).fetchall()
    done = 0
    total = 0
    sample: List[Dict[str, Any]] = []
    for r in rows:
        items = _safe_json(r["items"]) or []
        if not isinstance(items, list):
            continue
        for it in items:
            if not isinstance(it, dict):
                continue
            total += 1
            if it.get("checked"):
                done += 1
            if len(sample) < 12:
                sample.append(
                    {
                        "text": it.get("text", ""),
                        "checked": bool(it.get("checked", False)),
                        "source": it.get("source", "manual"),
                    }
                )
    percent = round(done / total * 100) if total else 0
    return {"done": done, "total": total, "percent": percent, "items": sample}


def _triage_section(conn, host_ids: List[int]) -> Dict[str, Any]:
    if not host_ids:
        return {"pending": 0, "running": 0, "done": 0, "failed": 0, "total": 0}
    placeholder = _in_clause(host_ids)
    rows = conn.execute(
        f"SELECT status, COUNT(*) c FROM triage_tasks WHERE host_id IN ({placeholder}) GROUP BY status",
        host_ids,
    ).fetchall()
    counts = {r["status"]: r["c"] for r in rows}
    return {
        "pending": counts.get("pending", 0),
        "running": counts.get("running", 0),
        "done": counts.get("done", 0),
        "failed": counts.get("failed", 0),
        "total": sum(counts.values()),
    }


def _ioc_section(conn, host_ids: List[int]):
    """返回 (ioc_summary, intel_by_ioc)."""
    if not host_ids:
        return [], {}
    placeholder = _in_clause(host_ids)
    hit_rows = conn.execute(
        f"""SELECT ioc_type, ioc_value, host_id, severity, COUNT(*) AS hit_count
            FROM ioc_hits
            WHERE host_id IN ({placeholder})
            GROUP BY ioc_type, ioc_value, host_id
            ORDER BY hit_count DESC LIMIT 30""",
        host_ids,
    ).fetchall()

    # 关联威胁情报
    value_keys = list({(r["ioc_type"], r["ioc_value"]) for r in hit_rows})
    ioc_id_by_value: Dict[tuple, int] = {}
    ioc_ids: List[int] = []
    if value_keys:
        vc = ",".join(["(?,?)"] * len(value_keys))
        params = [v for pair in value_keys for v in pair]
        ioc_rows = conn.execute(
            f"SELECT id, ioc_type, ioc_value FROM iocs WHERE (ioc_type, ioc_value) IN ({vc})",
            params,
        ).fetchall()
        for r in ioc_rows:
            ioc_id_by_value[(r["ioc_type"], r["ioc_value"])] = r["id"]
            ioc_ids.append(r["id"])

    intel_by_ioc: Dict[int, dict] = {}
    if ioc_ids:
        qm = _in_clause(ioc_ids)
        ti_rows = conn.execute(
            f"SELECT * FROM threat_intel WHERE ioc_id IN ({qm}) ORDER BY queried_at DESC",
            ioc_ids,
        ).fetchall()
        for r in ti_rows:
            ti = ThreatIntel._row_to_dict(r)
            ioc_id = ti.get("ioc_id")
            if ioc_id not in intel_by_ioc:
                intel_by_ioc[ioc_id] = ti

    ioc_summary: List[Dict[str, Any]] = []
    for h in hit_rows:
        ioc_id = ioc_id_by_value.get((h["ioc_type"], h["ioc_value"]))
        intel = intel_by_ioc.get(ioc_id) if ioc_id else None
        entry = {
            "ioc_type": h["ioc_type"],
            "ioc_value": h["ioc_value"],
            "host_id": h["host_id"],
            "severity": h["severity"],
            "hit_count": h["hit_count"],
            "intel": None,
        }
        if intel:
            entry["intel"] = {
                "provider": intel.get("provider"),
                "risk_score": intel.get("risk_score"),
                "judgments": intel.get("judgments"),
                "threat_level": intel.get("threat_level"),
                "attck": intel.get("attck"),
            }
        ioc_summary.append(entry)

    return ioc_summary, intel_by_ioc


def _ttp_section(conn, host_ids: List[int], intel_by_ioc: Dict[int, dict]):
    kill_chain: List[Dict[str, Any]] = []
    if host_ids:
        placeholder = _in_clause(host_ids)
        stage_rows = conn.execute(
            f"""SELECT attack_stage, COUNT(*) c FROM security_events
                WHERE host_id IN ({placeholder}) AND attack_stage IS NOT NULL
                GROUP BY attack_stage""",
            host_ids,
        ).fetchall()
        for r in stage_rows:
            stage = r["attack_stage"]
            kill_chain.append(
                {
                    "stage": stage,
                    "label": ATTACK_STAGE_LABELS.get(stage, stage),
                    "count": r["c"],
                }
            )

    # 技战术：从威胁情报 attck 字段聚合
    tech_counter: Dict[str, Dict[str, Any]] = {}
    for ti in intel_by_ioc.values():
        attck = ti.get("attck") or []
        if isinstance(attck, str):
            attck = _safe_json(attck) or []
        for a in attck or []:
            if isinstance(a, dict):
                tid = a.get("technique_id") or a.get("id") or str(a)
                name = a.get("name") or a.get("technique") or ""
            else:
                tid = str(a)
                name = ""
            if not tid or tid == "None":
                continue
            if tid not in tech_counter:
                tech_counter[tid] = {"technique_id": tid, "name": name, "count": 0}
            tech_counter[tid]["count"] += 1
    techniques = sorted(tech_counter.values(), key=lambda x: -x["count"])

    return {"kill_chain": kill_chain, "techniques": techniques}


def _ai_section(conn, host_ids: List[int]) -> Dict[str, Any]:
    if not host_ids:
        return {"risk_score": None, "attack_chain": None, "recommendation": None, "latest_at": None}
    placeholder = _in_clause(host_ids)
    rows = conn.execute(
        f"""SELECT ai_analysis, timestamp FROM security_events
            WHERE host_id IN ({placeholder})
              AND ai_analysis IS NOT NULL AND TRIM(ai_analysis) <> ''
            ORDER BY timestamp DESC LIMIT 10""",
        host_ids,
    ).fetchall()

    best = None
    for r in rows:
        raw = r["ai_analysis"]
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            parsed = str(raw)
        score = -1
        if isinstance(parsed, dict):
            score = parsed.get("risk_score") or parsed.get("riskScore") or -1
        if best is None or (isinstance(score, (int, float)) and score > best["_score"]):
            best = {"_score": score if isinstance(score, (int, float)) else -1,
                    "parsed": parsed, "at": r["timestamp"]}

    if not best:
        return {"risk_score": None, "attack_chain": None, "recommendation": None, "latest_at": None}

    parsed = best["parsed"]
    if isinstance(parsed, dict):
        return {
            "risk_score": parsed.get("risk_score") or parsed.get("riskScore"),
            "attack_chain": parsed.get("attack_chain") or parsed.get("attackChain"),
            "recommendation": parsed.get("recommendation") or parsed.get("summary"),
            "latest_at": best["at"],
        }
    return {
        "risk_score": None,
        "attack_chain": None,
        "recommendation": str(parsed)[:800],
        "latest_at": best["at"],
    }


def _timeline(conn, case: dict, host_ids: List[int]) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    name = case.get("name", "")

    def add(time, etype, title, detail):
        if time:
            events.append({"time": time, "type": etype, "title": title, "detail": detail})

    add(case.get("created_at"), "case", "案件创建", f"案件「{name}」建立")
    if host_ids:
        placeholder = _in_clause(host_ids)
        first_host = conn.execute(
            f"SELECT MIN(collection_time) m FROM hosts WHERE case_id = ? AND collection_time IS NOT NULL",
            (case.get("id"),),
        ).fetchone()
        add(first_host["m"], "host", "首批主机接入", "主机数据采集完成")
        first_alert = conn.execute(
            f"SELECT MIN(first_seen_at) m FROM alerts WHERE host_id IN ({placeholder})",
            host_ids,
        ).fetchone()
        add(first_alert["m"], "alert", "首次告警", "检测到第一条安全告警")
        triage_start = conn.execute(
            f"SELECT MIN(started_at) m FROM triage_tasks WHERE host_id IN ({placeholder}) AND started_at IS NOT NULL",
            host_ids,
        ).fetchone()
        add(triage_start["m"], "triage", "取证启动", "下发动态取证任务")
        triage_end = conn.execute(
            f"SELECT MAX(finished_at) m FROM triage_tasks WHERE host_id IN ({placeholder}) AND finished_at IS NOT NULL",
            host_ids,
        ).fetchone()
        add(triage_end["m"], "triage", "取证完成", "取证结果回传")
    rem_upd = conn.execute(
        "SELECT MAX(updated_at) m FROM remediation_checklist WHERE case_id = ?",
        (case.get("id"),),
    ).fetchone()
    add(rem_upd["m"], "remediation", "处置更新", "处置清单状态变更")
    updated = case.get("updated_at")
    if updated and updated != case.get("created_at"):
        add(updated, "case", "最近更新", "案件信息更新")

    events.sort(key=lambda e: e["time"] or "")
    return events
