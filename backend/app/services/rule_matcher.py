"""规则匹配引擎 — 对单条安全事件执行 7 种规则匹配.

支持匹配类型:
  - regex:      正则表达式匹配
  - list:       精确/包含列表匹配
  - composite:  AND/OR 子规则组合
  - behavior:   行为模式匹配（孤儿进程/浏览器子进程/高价值路径）
  - threshold:  数值阈值比较
  - exists:     字段存在性检查

灰度开关（P0-2 引擎合并）：
  USE_UNIFIED_ENGINE = True   → match_event 委派统一 RuleEngine.evaluate（设计 §1）
  USE_UNIFIED_ENGINE = False  → 回退旧实现（灰度回滚，保留壳 + 兼容现有测试）
旧 6 类内部 _match_* 实现保留为回退路径，不作为默认路径。
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

# ── 灰度开关 ──
USE_UNIFIED_ENGINE: bool = True


# ===================================================================
#  事件类型 → 候选规则分类映射
# ===================================================================

from app.rules.canonical_adapter import EVENT_TYPE_CATEGORY_MAP as _EVENT_TYPE_CATEGORY_MAP  # noqa: E402

# 保留旧名引用（向后兼容，供 test_event_type_map 等直接 import 使用）
_EVENT_TYPE_CATEGORY_MAP = _EVENT_TYPE_CATEGORY_MAP


# ===================================================================
#  主入口
# ===================================================================


def match_event(event: dict) -> list[dict]:
    """对单条 security_event 执行全部规则匹配（灰度开关）。

    默认（USE_UNIFIED_ENGINE=True）委派统一 RuleEngine.evaluate，
    支持 7 类 matcher + attack_chain + 抑制/误报/白名单闭环。
    回退（USE_UNIFIED_ENGINE=False）运行旧实现。

    Args:
        event: security_event 行字典（含 evidence JSON 字段）.

    Returns:
        命中的规则列表（含 gated_by 标记；空列表 = 未命中任何规则）.
    """
    if USE_UNIFIED_ENGINE:
        return _match_event_unified(event)
    return _match_event_legacy(event)


def _match_event_legacy(event: dict) -> list[dict]:
    """旧 match_event 实现（灰度回退路径，保留壳）。

    调用旧 6 类 _match_* 函数（读 evidence 嵌套字段），
    无 attack_chain / 抑制/误报/白名单能力。
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


def _match_event_unified(event: dict) -> list[dict]:
    """统一匹配入口：security_events 行 → CanonicalEvent → RuleEngine.evaluate.

    实时候选按 event_type→category 预筛；门控逻辑（抑制/误报/白名单）
    与分析链路完全一致，attack_chain 实时可用。
    """
    from app.rules.canonical_adapter import (
        EVENT_TYPE_CATEGORY_MAP,
        security_event_row_to_canonical,
    )

    canonical = security_event_row_to_canonical(event)
    item = canonical.to_engine_item()
    event_type = canonical.event_type

    cats = EVENT_TYPE_CATEGORY_MAP.get(event_type)
    if not cats:
        return []

    from app.rules.rule_engine import RuleEngine
    from app.rules.detection_policy import DetectionPolicy

    rules = RuleEngine.load_rules_by_categories(cats)
    if not rules:
        return []

    global_context = {
        "host_id": canonical.host_id,
        "all_items": [item],
        "process_map": {},
        "connections": item.get("connections") or [],
    }

    matches = RuleEngine.evaluate(
        [item],
        rules,
        global_context=global_context,
        policy=DetectionPolicy(mode="realtime"),
    )

    # 翻译统一 MatchedRule dict → 旧 match_event 输出格式（含 gated_by）
    result = []
    for m in matches:
        result.append({
            "rule_id": m.get("rule_id"),
            "rule_name": m.get("rule_name"),
            "rule_type": m.get("rule_type"),
            "category": m.get("category"),
            "severity": m.get("severity"),
            "confidence": m.get("confidence"),
            "matched_fields": m.get("matched_fields") or {},
            "gated_by": m.get("gated_by"),
        })
    return result


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
        parent_name = str(evidence.get("parent_name") or evidence.get("parent_process_name") or "").lower().strip()
        # ppid 为 0/4 表示父进程已退出或系统级，属可疑孤儿——与父进程名无关，优先判定。
        if ppid == 0 or ppid == 4:
            return {"confidence": 0.75, "matched_fields": {"ppid": ppid, "parent_name": parent_name}}
        # 其余情况：无父进程信息（None / 空串）→ 无法判定孤儿，必须跳过。
        # 修复：原逻辑 str(None)=="none" 导致 "explorer" not in "none" 恒 True，
        # 所有无父进程名的事件被误判为孤儿进程。
        if not parent_name:
            return None
        # 父进程不在已知合法父进程列表中 → 疑似孤儿（忽略 .exe 等扩展名）
        base = parent_name.rsplit(".", 1)[0] if "." in parent_name else parent_name
        KNOWN_LEGIT_PARENTS = (
            "explorer", "wininit", "services", "system", "svchost", "csrss",
            "lsass", "smss", "winlogon", "taskhostw", "taskhost", "dwm",
            "sihost", "conhost", "rundll32", "lsm", "runtimebroker",
        )
        if parent_name in KNOWN_LEGIT_PARENTS or base in KNOWN_LEGIT_PARENTS:
            return None
        return {"confidence": 0.6, "matched_fields": {"ppid": ppid, "parent_name": parent_name}}

    elif pattern == "child_of_office":
        parent = str(evidence.get("parent_name") or evidence.get("parent_process_name") or "").lower().strip()
        if not parent:
            return None
        if any(x in parent for x in ["winword", "excel", "powerpnt", "outlook", "wordpad"]):
            return {"confidence": 0.85, "matched_fields": {"parent_name": parent}}
        return None

    elif pattern == "child_of_browser":
        parent = str(evidence.get("parent_name") or evidence.get("parent_process_name") or "").lower().strip()
        if not parent:
            return None
        if any(x in parent for x in ["chrome", "firefox", "msedge", "iexplore", "opera"]):
            return {"confidence": 0.80, "matched_fields": {"parent_name": parent}}
        return None

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
