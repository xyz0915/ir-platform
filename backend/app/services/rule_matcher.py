"""规则匹配引擎 — 对单条安全事件执行 7 种规则匹配.

支持匹配类型:
  - regex:      正则表达式匹配
  - list:       精确/包含列表匹配
  - composite:  AND/OR 子规则组合
  - behavior:   行为模式匹配（孤儿进程/浏览器子进程/高价值路径）
  - threshold:  数值阈值比较
  - exists:     字段存在性检查
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Optional

from app.database import get_connection

logger = logging.getLogger(__name__)

# ── 缓存配置 ──
_rule_cache: dict[str, dict] = {}
_RULE_CACHE_TTL = 60  # 秒


# ===================================================================
#  事件类型 → 候选规则分类映射
# ===================================================================

_EVENT_TYPE_CATEGORY_MAP: dict[str, list[str]] = {
    "process_start":        ["process", "execution", "defense_evasion"],
    "process_terminate":    ["process", "defense_evasion"],
    "network_outbound":     ["network", "exfiltration", "lateral", "ioc"],
    "network_listen":       ["network", "persistence"],
    "dns_query":            ["network", "exfiltration"],
    "registry_modify":      ["persistence", "privilege_escalation"],
    "registry_delete":      ["defense_evasion"],
    "persistence_register": ["persistence", "startup"],
    "file_create":          ["execution", "webshell", "impact"],
    "file_modify":          ["execution", "impact"],
    "file_create":          ["execution", "webshell", "impact"],
    "user_login":           ["credential", "lateral"],
    "user_logout":          ["credential"],
    "service_operation":    ["persistence", "privilege_escalation"],
    "wmi_subscribe":        ["execution", "persistence"],
    "scheduled_task":       ["persistence", "execution"],
    "driver_load":          ["persistence", "execution"],
    "module_load":          ["defense_evasion"],
    "pipe_connect":         ["lateral", "execution"],
    "behavior_alert":       ["process", "execution"],
    "ioc_match":            ["ioc"],
}


# ===================================================================
#  主入口
# ===================================================================


def match_event(event: dict) -> list[dict]:
    """对单条 security_event 执行全部规则匹配.

    Args:
        event: security_event 行字典（含 evidence JSON 字段）.

    Returns:
        命中的规则列表（空列表 = 未命中任何规则）.
    """
    evidence = _parse_evidence(event.get("evidence", "{}"))
    event_type = event.get("event_type", "")

    # 1. 根据 event_type 确定候选规则分类
    candidates = _get_candidate_rules(event_type)
    if not candidates:
        return []

    # 2. 逐条匹配
    matched: list[dict] = []
    for rule in candidates:
        try:
            result = _match_single_rule(rule, evidence, event)
            if result:
                matched.append(result)
        except Exception as exc:
            logger.debug("规则匹配异常 rule_id=%s: %s", rule.get("id"), exc)

    return matched


# ===================================================================
#  辅助函数
# ===================================================================


def _parse_evidence(raw: Any) -> dict:
    """将 evidence 字段解析为字典."""
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw) if raw else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _get_candidate_rules(event_type: str) -> list[dict]:
    """根据事件类型获取候选规则分类，并从数据库加载已启用规则."""
    cats = _EVENT_TYPE_CATEGORY_MAP.get(event_type, [])
    if not cats:
        return []
    return _load_rules_by_categories(cats)


def _load_rules_by_categories(categories: list[str]) -> list[dict]:
    """按分类从数据库加载已启用的规则（带 LRU 缓存，TTL 60s）.

    Args:
        categories: 规则分类列表.

    Returns:
        规则字典列表（已解析 condition JSON）.
    """
    cache_key = ",".join(sorted(categories))
    now = time.time()
    if cache_key in _rule_cache:
        entry = _rule_cache[cache_key]
        if now - entry["ts"] < _RULE_CACHE_TTL:
            return entry["rules"]

    placeholders = ",".join("?" * len(categories))
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT id, name, rule_type, category, severity, condition FROM rules "
            f"WHERE enabled=1 AND category IN ({placeholders})",
            categories,
        ).fetchall()

    rules: list[dict] = []
    for r in rows:
        rule = dict(r)
        cond = rule.get("condition")
        if isinstance(cond, str):
            try:
                rule["condition"] = json.loads(cond)
            except json.JSONDecodeError:
                logger.warning("规则 %d condition 解析失败", rule["id"])
                continue
        if rule.get("rule_type") == "attack_chain":
            continue  # 攻击链规则单独处理
        rules.append(rule)

    _rule_cache[cache_key] = {"rules": rules, "ts": now}
    return rules


def _get_nested(data: dict, field_path: str) -> Any:
    """从字典中读取嵌套字段，支持点号分隔的路径.

    Args:
        data: 目标字典.
        field_path: 字段路径，如 "process.parent.name".

    Returns:
        字段值，路径不存在返回 None.
    """
    parts = field_path.split(".")
    val: Any = data
    for p in parts:
        if isinstance(val, dict):
            val = val.get(p)
        else:
            return None
    return val


# ===================================================================
#  单条规则匹配分发
# ===================================================================


def _match_single_rule(rule: dict, evidence: dict, event: dict) -> Optional[dict]:
    """执行单条规则匹配，返回匹配结果或 None."""
    rule_type = rule["rule_type"]
    condition = rule.get("condition", {}) or {}

    match_result: Optional[dict] = None

    if rule_type == "regex":
        match_result = _match_regex(condition, evidence)
    elif rule_type == "list":
        match_result = _match_list(condition, evidence)
    elif rule_type == "composite":
        match_result = _match_composite(condition, evidence)
    elif rule_type == "behavior":
        match_result = _match_behavior(condition, evidence, event)
    elif rule_type == "threshold":
        match_result = _match_threshold(condition, event, evidence)
    elif rule_type == "exists":
        match_result = _match_exists(condition, evidence)

    if match_result:
        return {
            "rule_id": rule["id"],
            "rule_name": rule["name"],
            "rule_type": rule_type,
            "category": rule.get("category"),
            "severity": rule.get("severity", event.get("severity", "info")),
            "confidence": match_result.get("confidence", 0.8),
            "matched_fields": match_result.get("matched_fields", {}),
        }
    return None


# ===================================================================
#  7 种匹配实现
# ===================================================================


def _match_regex(condition: dict, evidence: dict) -> Optional[dict]:
    """正则匹配：检查 evidence 中指定字段是否匹配正则表达式.

    condition 格式:
        {"field": "process_name", "pattern": "powershell\\.exe", "flags": "ignorecase"}
    """
    field = condition.get("field", "")
    pattern = condition.get("pattern", "")
    flags = condition.get("flags", "")
    field_value = _get_nested(evidence, field)
    if field_value is None:
        return None
    re_flags = re.IGNORECASE if "ignorecase" in flags else 0
    match = re.search(pattern, str(field_value), re_flags)
    if match:
        return {"confidence": 0.9, "matched_fields": {field: match.group()[:120]}}
    return None


def _match_list(condition: dict, evidence: dict) -> Optional[dict]:
    """列表匹配：检查 evidence 中指定字段是否在/包含列表中的值.

    condition 格式:
        {"field": "process_name", "values": ["cmd.exe", "powershell.exe"], "match_mode": "exact"}
    match_mode: "exact"（精确匹配）或 "contains"（包含匹配）
    """
    field = condition.get("field", "")
    values = condition.get("values", [])
    mode = condition.get("match_mode", "exact")
    field_value = _get_nested(evidence, field)
    if field_value is None:
        return None

    str_val = str(field_value)
    if mode == "exact":
        if field_value in values or str_val in values:
            return {"confidence": 1.0, "matched_fields": {field: str_val[:120]}}
    elif mode == "contains":
        for v in values:
            if v in str_val:
                return {"confidence": 0.9, "matched_fields": {field: v}}
    return None


def _match_composite(condition: dict, evidence: dict) -> Optional[dict]:
    """组合匹配：AND/OR 逻辑组合多条子规则.

    condition 格式:
        {"logic": "AND", "sub_rules": [
            {"type": "regex", "field": "name", "pattern": "powershell\\.exe"},
            {"type": "regex", "field": "command_line", "pattern": "-enc"}
        ]}
    """
    logic = condition.get("logic", "AND")
    sub_rules = condition.get("sub_rules", [])
    results: list[dict] = []

    for sub in sub_rules:
        result = _match_simple_sub_rule(sub, evidence)
        if result:
            results.append(result)

    if logic == "AND" and len(results) == len(sub_rules):
        return {
            "confidence": min(r["confidence"] for r in results),
            "matched_fields": {
                k: v for r in results for k, v in r["matched_fields"].items()
            },
        }
    elif logic == "OR" and results:
        return {
            "confidence": max(r["confidence"] for r in results),
            "matched_fields": {
                k: v for r in results for k, v in r["matched_fields"].items()
            },
        }
    return None


def _match_simple_sub_rule(sub: dict, evidence: dict) -> Optional[dict]:
    """子规则匹配（composite 内部使用）.

    支持子规则类型: regex（默认）, list, exists
    """
    sub_type = sub.get("type", "regex")
    field = sub.get("field", "")
    field_value = _get_nested(evidence, field)
    if field_value is None:
        return None

    if sub_type == "list":
        values = sub.get("values", [])
        mode = sub.get("match_mode", "exact")
        str_val = str(field_value)
        if mode == "exact":
            if field_value in values or str_val in values:
                return {"confidence": 1.0, "matched_fields": {field: str_val[:100]}}
        elif mode == "contains":
            for v in values:
                if v in str_val:
                    return {"confidence": 0.9, "matched_fields": {field: v}}
        return None

    # regex (default) / exists
    if sub_type == "exists":
        if field_value is not None and field_value != "" and field_value != [] and field_value != {}:
            return {"confidence": 0.7, "matched_fields": {field: "present"}}
        return None

    # regex
    pattern = sub.get("pattern", "")
    if not pattern:
        return None
    re_flags = re.IGNORECASE if "ignorecase" in str(sub.get("flags", "")) else 0
    match = re.search(pattern, str(field_value), re_flags)
    if match:
        return {"confidence": 0.9, "matched_fields": {field: match.group()[:100]}}
    return None


def _match_behavior(condition: dict, evidence: dict, event: dict) -> Optional[dict]:
    """行为模式匹配：孤儿进程 / 浏览器子进程 / 高价值路径 / Office 子进程.

    condition 格式:
        {"pattern": "orphan_process"}  等
    """
    pattern = condition.get("pattern", "")

    if pattern == "orphan_process":
        ppid = evidence.get("ppid")
        parent_name = str(evidence.get("parent_name", "")).lower()
        parent_process_name = str(evidence.get("parent_process_name", "")).lower()
        combined_parent = parent_name or parent_process_name
        if ppid == 0 or ppid == 4 or (
            "explorer" not in combined_parent
            and "wininit" not in combined_parent
            and "services" not in combined_parent
        ):
            return {"confidence": 0.75, "matched_fields": {"ppid": ppid}}

    elif pattern == "child_of_office":
        parent = str(evidence.get("parent_name", "")).lower()
        parent_process = str(evidence.get("parent_process_name", "")).lower()
        combined = parent or parent_process
        if any(x in combined for x in ["winword", "excel", "powerpnt", "outlook", "wordpad"]):
            return {"confidence": 0.85, "matched_fields": {"parent_name": combined}}

    elif pattern == "child_of_browser":
        parent = str(evidence.get("parent_name", "")).lower()
        parent_process = str(evidence.get("parent_process_name", "")).lower()
        combined = parent or parent_process
        if any(x in combined for x in ["chrome", "firefox", "msedge", "iexplore", "opera"]):
            return {"confidence": 0.80, "matched_fields": {"parent_name": combined}}

    elif pattern == "high_value_path":
        path = str(evidence.get("process_path", "")).lower()
        if any(x in path for x in [r"\temp", r"\tmp", r"\downloads", r"\appdata\local\temp"]):
            return {"confidence": 0.70, "matched_fields": {"process_path": path[:80]}}

    return None


def _match_threshold(condition: dict, event: dict, evidence: dict) -> Optional[dict]:
    """阈值匹配：比较数值字段是否满足阈值条件.

    condition 格式:
        {"field": "risk_score", "operator": ">", "value": 50}
    operator: >, >=, <, <=
    """
    field = condition.get("field", "")
    operator = condition.get("operator", ">")
    value = condition.get("value", 0)

    # 先从 event 顶层取，再从 evidence 取
    field_value = event.get(field) or _get_nested(evidence, field)
    if field_value is None:
        return None

    try:
        field_value = float(field_value)
        threshold = float(value)
        if (operator == ">" and field_value > threshold) or \
           (operator == ">=" and field_value >= threshold) or \
           (operator == "<" and field_value < threshold) or \
           (operator == "<=" and field_value <= threshold):
            return {"confidence": 0.8, "matched_fields": {field: field_value}}
    except (ValueError, TypeError):
        pass
    return None


def _match_exists(condition: dict, evidence: dict) -> Optional[dict]:
    """存在性匹配：检查指定字段是否存在且非空.

    condition 格式:
        {"field": "scheduled_task_xml"}
    """
    field = condition.get("field", "")
    field_value = _get_nested(evidence, field)
    if field_value is not None and field_value != "" and field_value != [] and field_value != {}:
        return {"confidence": 0.7, "matched_fields": {field: "present"}}
    return None
