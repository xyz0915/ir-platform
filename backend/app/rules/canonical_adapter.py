"""CanonicalAdapter — security_events 行 → CanonicalEvent → 引擎扁平 item 适配层.

设计 §1 / §3 / T-P0-1：
  - security_event_row_to_canonical(): 将 security_events 行映射为 CanonicalEvent，
    作为实时与分析链路的**唯一输入契约**。
  - CanonicalEvent.to_engine_item(): 把嵌套 evidence 扁平化为 RuleEngine 期望的
    字段（name/path/ppid/command_line/remote_address/...），供 MatcherRegistry 消费。
  - EVENT_TYPE_CATEGORY_MAP: 实时候选预筛路由（保留自 services/rule_matcher），
    按 event_type 预筛候选规则类别以保性能，降级开关可退回全量（与分析一致）。
  - build_realtime_global_context(): 构造实时链路 global_context（host_id /
    process_map / all_items / connections），attack_chain 按 host_id 下钻关联。

实时与分析两链路共用同一 RuleEngine.evaluate 入口，唯一差异是候选范围
（实时按 category 预筛、分析全量），门控逻辑完全一致 → 结果一致性由构造保证。
"""

from __future__ import annotations

from typing import Optional

from app.services.canonical_event import (
    CanonicalEvent,
    security_event_row_to_canonical as _row_to_canonical,
)


# ── 事件类型 → 候选规则分类映射（实时候选预筛）──────────────────────────
# 进程类事件额外接入 "behavior" 分类，使孤儿进程/浏览器子进程/高价值路径等行为规则
# 能够作为候选规则加载（修复：此前无任何 event_type 路由到 behavior，导致行为规则永不执行）。
EVENT_TYPE_CATEGORY_MAP: dict[str, list[str]] = {
    "process_start":        ["process", "execution", "defense_evasion", "behavior"],
    "process_terminate":    ["process", "defense_evasion", "behavior"],
    "network_outbound":     ["network", "exfiltration", "lateral", "ioc"],
    "network_listen":       ["network", "persistence"],
    "dns_query":            ["network", "exfiltration"],
    "registry_modify":      ["persistence", "privilege_escalation"],
    "registry_delete":      ["defense_evasion"],
    "persistence_register": ["persistence", "startup"],
    "file_create":          ["execution", "webshell", "impact"],
    "file_modify":          ["execution", "impact"],
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


def security_event_row_to_canonical(row: dict) -> CanonicalEvent:
    """将 security_events 行映射为 CanonicalEvent（统一输入契约）.

    Args:
        row: security_events 表行字典（含 evidence JSON 字段、host_id、event_type 等）.

    Returns:
        CanonicalEvent 实例。
    """
    return _row_to_canonical(row)


def build_realtime_global_context(canonical: CanonicalEvent, item: dict) -> dict:
    """构造实时链路的 global_context.

    实时单事件无完整进程树，process_map 留空（行为规则按 ppid 退化判定）；
    attack_chain 仍按 host_id 下钻历史取证数据关联。

    Args:
        canonical: 由 security_events 行构造的 CanonicalEvent。
        item: to_engine_item() 产出的扁平化数据项。

    Returns:
        global_context 字典（host_id / all_items / process_map / connections）。
    """
    return {
        "host_id": canonical.host_id,
        "all_items": [item],
        "process_map": {},
        "connections": item.get("connections") or [],
    }
