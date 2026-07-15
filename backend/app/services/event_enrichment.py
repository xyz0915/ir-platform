"""分析中心事件富化服务 — 风险评分、影响评估、处置建议、主机统计、上下文."""

import json
import logging
from typing import Optional

from app.database import get_connection

logger = logging.getLogger(__name__)

# 高危路径列表（非 raw string，避免尾随反斜杠语法错误）
HIGH_RISK_PATHS = [
    "\\TEMP\\",
    "\\AppData\\Local\\Temp\\",
    "\\AppData\\Roaming\\Microsoft\\Windows\\Start Menu",
    "\\Startup",
    "\\Users\\Public\\",
]
SENSITIVE_PATHS = [
    "\\System32\\",
    "\\SysWOW64\\",
    "\\Windows\\System\\",
    "\\ProgramData\\",
]
PERSISTENCE_REG_PATHS = [
    "\\CurrentVersion\\Run",
    "\\CurrentVersion\\RunOnce",
    "\\CurrentVersion\\RunServices",
    "\\Windows\\CurrentVersion\\Run",
]


def calculate_risk_score(event: dict) -> int:
    """风险评分 0-100"""
    severity_weights = {"critical": 80, "high": 60, "medium": 40, "low": 20, "info": 5}
    score = severity_weights.get(event.get("severity", "info"), 5)

    # 命中规则加分
    matched_rules = event.get("matched_rules", [])
    if isinstance(matched_rules, str):
        try:
            matched_rules = json.loads(matched_rules)
        except Exception:
            matched_rules = []
    if matched_rules:
        score += min(len(matched_rules) * 5, 25)

    # IOC 命中加分
    ioc_matches = event.get("ioc_matches", [])
    if isinstance(ioc_matches, str):
        try:
            ioc_matches = json.loads(ioc_matches)
        except Exception:
            ioc_matches = []
    if ioc_matches:
        score += min(len(ioc_matches) * 15, 30)

    # 路径风险
    evidence = event.get("evidence", {})
    if isinstance(evidence, str):
        try:
            evidence = json.loads(evidence)
        except Exception:
            evidence = {}

    path_risk = _check_path_risk(evidence)
    if path_risk == "high":
        score += 15
    elif path_risk == "sensitive":
        score += 8

    return max(0, min(100, score))


def _check_path_risk(evidence: dict) -> str:
    for key in ["file_path", "process_path", "key_path", "command_line"]:
        val = evidence.get(key, "")
        if val:
            val_upper = val.upper()
            for p in HIGH_RISK_PATHS:
                if p.upper() in val_upper:
                    return "high"
            for p in SENSITIVE_PATHS:
                if p.upper() in val_upper:
                    return "sensitive"
    return "normal"


def assess_impact_scope(event_id: str) -> dict:
    """评估影响范围"""
    with get_connection() as conn:
        # 先找到该事件的主机
        row = conn.execute("SELECT host_id, evidence FROM security_events WHERE id=?", (event_id,)).fetchone()
        if not row:
            return {"same_host_events": 0, "same_ip_hosts": 0, "users_involved": 0, "sensitive_paths": 0}

        host_id = row["host_id"]
        evidence = row["evidence"]
        if isinstance(evidence, str):
            try:
                evidence = json.loads(evidence)
            except Exception:
                evidence = {}

        # 1. 同一主机关联事件数（过去 30 分钟）
        same_host = conn.execute(
            "SELECT COUNT(*) as cnt FROM security_events WHERE host_id=? AND timestamp >= datetime('now', '-30 minutes')",
            (host_id,),
        ).fetchone()["cnt"]

        # 2. 找出该事件涉及的所有 remote_address（如果是网络事件）
        remote_addr = evidence.get("remote_address", "")
        same_ip = 0
        if remote_addr:
            same_ip = conn.execute(
                "SELECT COUNT(DISTINCT se.host_id) as cnt FROM security_events se "
                "WHERE se.evidence LIKE ?",
                (f"%{remote_addr}%",),
            ).fetchone()["cnt"]

        # 3. 涉及账号
        user_name = evidence.get("user_name", "")
        users_involved = 1 if user_name else 0

        # 4. 敏感路径
        file_path = evidence.get("file_path", "") or evidence.get("process_path", "")
        fp_upper = (file_path or "").upper()
        sensitive_paths = 1 if any(p.upper() in fp_upper for p in HIGH_RISK_PATHS + SENSITIVE_PATHS) else 0

        # 5. 同进程名在其他主机上出现
        process_name = evidence.get("process_name", "")
        same_process_hosts = (
            conn.execute(
                "SELECT COUNT(DISTINCT se.host_id) as cnt FROM security_events se "
                "WHERE se.evidence LIKE ?",
                (f"%\"process_name\": \"{process_name}\"%",),
            ).fetchone()["cnt"]
            if process_name
            else 0
        )

        return {
            "same_host_events": same_host,
            "same_ip_hosts": same_ip,
            "users_involved": users_involved,
            "sensitive_paths": sensitive_paths,
            "same_process_hosts": same_process_hosts,
        }


def generate_remediation(event: dict) -> list:
    """动态处置建议"""
    steps = []
    event_type = event.get("event_type", "")
    evidence = event.get("evidence", {})
    if isinstance(evidence, str):
        try:
            evidence = json.loads(evidence)
        except Exception:
            evidence = {}

    if event_type in ("process_start", "process_terminate"):
        pid = evidence.get("pid", "")
        path = evidence.get("process_path", "")
        steps.append({
            "step": 1,
            "title": "结束恶意进程",
            "command": f"taskkill /PID {pid} /F" if pid else "taskkill /IM process_name /F",
            "risk": "low",
        })
        if path:
            steps.append({"step": 2, "title": "删除恶意文件", "command": f'del /F "{path}"', "risk": "medium"})

    if event_type in ("registry_modify", "registry_delete"):
        key = evidence.get("key_path", "")
        value = evidence.get("value_name", "")
        if key:
            cmd = f'reg delete "{key}"'
            if value:
                cmd += f" /V {value}"
            cmd += " /F"
            steps.append({
                "step": len(steps) + 1,
                "title": "清理注册表持久化",
                "command": cmd,
                "risk": "medium",
            })

    if event_type in ("network_outbound",):
        addr = evidence.get("remote_address", "")
        if addr:
            steps.append({
                "step": len(steps) + 1,
                "title": "防火墙阻断 C2 通信",
                "command": f'netsh advfirewall firewall add rule name="Block C2" dir=out remoteip={addr} action=block',
                "risk": "low",
            })

    if event_type in ("file_create", "file_modify"):
        path = evidence.get("file_path", "")
        if path:
            steps.append({
                "step": len(steps) + 1,
                "title": "删除恶意文件",
                "command": f'del /F "{path}"',
                "risk": "medium",
            })

    # 默认：隔离主机
    if not steps:
        steps.append({
            "step": 1,
            "title": "隔离受感染主机",
            "command": "netsh advfirewall set allprofiles state on && net stop Server",
            "risk": "medium",
        })

    return steps


def get_host_stats(host_id: int) -> dict:
    """主机 24h 统计"""
    with get_connection() as conn:
        stats = conn.execute(
            "SELECT COUNT(*) as total FROM security_events WHERE host_id=? AND timestamp >= datetime('now', '-1 day', '+8 hours')",
            (host_id,),
        ).fetchone()["total"]

        matched = conn.execute(
            "SELECT COUNT(*) as cnt FROM security_events "
            "WHERE host_id=? AND matched_rules IS NOT NULL AND matched_rules != '[]' "
            "AND timestamp >= datetime('now', '-1 day', '+8 hours')",
            (host_id,),
        ).fetchone()["cnt"]

        active = conn.execute(
            "SELECT COUNT(*) as cnt FROM security_events "
            "WHERE host_id=? AND status IN ('pending', 'triaging', 'investigating')",
            (host_id,),
        ).fetchone()["cnt"]

        # 上次处置记录
        last_disp = conn.execute(
            "SELECT d.action, d.operator, d.comment, d.created_at "
            "FROM event_disposition_log d "
            "JOIN security_events e ON d.event_id = e.id "
            "WHERE e.host_id = ? "
            "ORDER BY d.created_at DESC LIMIT 1",
            (host_id,),
        ).fetchone()

        result = {"total_24h": stats, "matched_24h": matched, "active_alerts": active}
        if last_disp:
            result["last_disposition"] = {
                "action": last_disp["action"],
                "operator": last_disp["operator"],
                "comment": last_disp["comment"],
                "at": last_disp["created_at"],
            }

        return result


def get_event_context(event_id: str, minutes: int = 5) -> list:
    """获取事件前后 N 分钟同一主机的事件"""
    with get_connection() as conn:
        event = conn.execute("SELECT id, host_id, timestamp FROM security_events WHERE id=?", (event_id,)).fetchone()
        if not event:
            return []

        events = conn.execute(
            "SELECT id, event_type, severity, timestamp, host_id, "
            "substr(evidence,1,200) as evidence_snippet "
            "FROM security_events "
            "WHERE host_id=? AND id != ? "
            "AND timestamp >= datetime(?, '-' || ? || ' minutes') "
            "AND timestamp <= datetime(?, '+' || ? || ' minutes') "
            "ORDER BY timestamp ASC",
            (event["host_id"], event_id, event["timestamp"], minutes, event["timestamp"], minutes),
        ).fetchall()

        result = []
        for r in events:
            d = dict(r)
            # 提取摘要
            ev = d.get("evidence_snippet", "")
            if ev:
                try:
                    ev_data = json.loads(ev)
                except Exception:
                    ev_data = {}
            else:
                ev_data = {}
            d["summary"] = _build_context_summary(d["event_type"], ev_data)
            result.append(d)
        return result


def _build_context_summary(event_type: str, evidence: dict) -> str:
    """构建时间线事件的摘要"""
    if event_type in ("process_start",):
        return f"{evidence.get('process_name', '?')} (PID:{evidence.get('pid', '?')})"
    if event_type in ("network_outbound", "network_listen"):
        return f"{evidence.get('remote_address', '?')}:{evidence.get('remote_port', '?')}"
    if event_type in ("file_create", "file_modify"):
        return f"{evidence.get('file_name', evidence.get('file_path', '?'))}"
    if event_type in ("registry_modify", "registry_delete"):
        return f"{evidence.get('key_path', '?')}"
    if event_type in ("user_login",):
        return f"{evidence.get('user_name', '?')} from {evidence.get('source_ip', '?')}"
    if event_type in ("dns_query",):
        return f"{evidence.get('query', '?')}"
    return event_type
