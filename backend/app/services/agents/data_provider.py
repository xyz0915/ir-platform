"""Agent 数据域访问辅助（只读）— 供四个专职 Agent 复用（§4 / §8）。

所有函数均为只读查询，指向真实数据域：
- security_events（含 ai_verdict JSON）
- normalized_logs（范式化日志）
- process_events（进程事件，用于攻击链回溯）
- hosts（主机画像）
- rules（命中规则，用于分诊参考）
- KnowledgeRetriever（cases RAG 检索）

绝不修改任何数据；脱敏在调用方（Agent 输出）经 data_masking.apply 处理。
"""

import json
import logging
from typing import Any, Optional

from app.database import get_connection

logger = logging.getLogger(__name__)


def _json_loads(value: Any, default: Any = None) -> Any:
    """安全 JSON 解析（失败返回 default）。"""
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


def get_event(event_id: str) -> Optional[dict]:
    """按 id 获取单条安全事件。"""
    if not event_id:
        return None
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM security_events WHERE id = ?", (event_id,)
        ).fetchone()
    return dict(row) if row else None


def get_events(event_ids: list[str]) -> list[dict]:
    """批量获取安全事件。"""
    if not event_ids:
        return []
    placeholders = ",".join("?" for _ in event_ids)
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT * FROM security_events WHERE id IN ({placeholders})",
            tuple(event_ids),
        ).fetchall()
    return [dict(r) for r in rows]


def get_logs_by_host(host_id: int, limit: int = 200) -> list[dict]:
    """获取主机的范式化日志（按时间升序），用于分诊/调查证据。"""
    if not host_id:
        return []
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM normalized_logs WHERE host_id = ? "
            "ORDER BY timestamp ASC LIMIT ?",
            (host_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def get_process_events(host_id: int, limit: int = 500) -> list[dict]:
    """获取主机的进程事件（按事件时间升序），用于攻击链/根因回溯。"""
    if not host_id:
        return []
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM process_events WHERE host_id = ? "
            "ORDER BY COALESCE(event_time, start_time) ASC LIMIT ?",
            (host_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def get_host(host_id: int) -> Optional[dict]:
    """获取主机画像。"""
    if not host_id:
        return None
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, case_id, hostname, ip_address, os_type, os_version, status "
            "FROM hosts WHERE id = ?", (host_id,)
        ).fetchone()
    return dict(row) if row else None


def get_enabled_rules(limit: int = 50) -> list[dict]:
    """获取已启用的检测规则（分诊参考命中规则）。"""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, name, category, severity, description FROM rules "
            "WHERE enabled = 1 ORDER BY severity DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_rules_hit_summary(event: dict, rules: list[dict]) -> str:
    """根据事件特征匹配可能命中的规则，返回人读摘要（不写库、不虚构）。

    匹配策略：规则 category / name 命中 event_type 或 event 文本的，按 severity 列示。
    这是"参考命中"，而非运行时真实命中，仅用于分诊上下文。
    """
    if not event or not rules:
        return ""
    text_blob = " ".join(str(v) for v in event.values() if isinstance(v, (str, int)))
    etype = (event.get("event_type") or "").lower()
    hits: list[str] = []
    for rule in rules:
        category = (rule.get("category") or "").lower()
        name = (rule.get("name") or "").lower()
        desc = (rule.get("description") or "").lower()
        if etype and (etype in category or etype in name or etype in desc):
            hits.append(f"[{rule.get('severity')}] {rule.get('name')}")
        elif name and name in text_blob.lower():
            hits.append(f"[{rule.get('severity')}] {rule.get('name')}")
    if not hits:
        return "（无直接命中的已知规则）"
    return "; ".join(hits[:10])


def retrieve_cases(query_text: str, limit: int = 5) -> list[dict]:
    """经 KnowledgeRetriever 检索历史案例（RAG）。

    失败时返回空列表（不阻断调查链路）。
    """
    try:
        from app.services.knowledge_retriever import KnowledgeRetriever
        results = KnowledgeRetriever.retrieve(
            {"_raw_data": {"query": query_text}}, limit=limit, structured=True
        )
        if isinstance(results, list):
            return results
    except Exception as exc:  # noqa: BLE001
        logger.warning("RAG 检索失败（降级为空）: %s", exc)
    return []


def extract_event_refs(events: list[dict]) -> list[dict]:
    """构造安全事件 evidence refs。"""
    refs = []
    for e in events:
        refs.append({
            "type": "security_events",
            "ref": f"security_events.id={e.get('id')}",
            "severity": e.get("severity"),
            "event_type": e.get("event_type"),
        })
    return refs


def extract_log_refs(logs: list[dict], max_refs: int = 20) -> list[dict]:
    """构造范式化日志 evidence refs（含 MITRE / 严重度线索）。"""
    refs = []
    for log in logs[:max_refs]:
        refs.append({
            "type": "normalized_logs",
            "ref": f"normalized_logs.id={log.get('id')}",
            "event_type": log.get("event_type"),
            "severity": log.get("severity"),
            "mitre_attack": log.get("mitre_attack"),
        })
    return refs


def extract_process_refs(procs: list[dict], max_refs: int = 20) -> list[dict]:
    """构造进程事件 evidence refs。"""
    refs = []
    for p in procs[:max_refs]:
        refs.append({
            "type": "process_events",
            "ref": f"process_events.id={p.get('id')}",
            "process_name": p.get("process_name"),
            "pid": p.get("pid"),
            "parent_name": p.get("parent_name"),
        })
    return refs
