"""规则 → 动态 IOC 情报依赖巡检（P0-1）.

P0-1 把 ``suspicious_c2_domain`` 等规则里的占位虚构 IOC（``*.example.com``）
全部移除，改为完全依赖 ``iocs`` 表的动态情报。这样做消除了"虚假覆盖"，
但引入了一个**新的隐性风险**：如果运营方从未导入任何情报，这些规则虽然
``enabled=true``，实际仍然零命中。

本模块把这个隐性依赖**显性化、可观测化**：扫描所有依赖动态 IOC 的规则，
逐条给出"它需要哪些类型的情报"以及"当前情报库是否满足"，供 UI 与巡检使用。
"""

import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def _iter_list_conditions(rule: dict):
    """产出规则中所有 list 型条件（含 attack_chain 各步骤中的 list match）.

    Yields:
        (path, condition_dict) 二元组，path 用于定位来源，如 "condition"
        或 "condition.ordered_steps[2].match"。
    """
    condition = rule.get("condition")
    if isinstance(condition, str):
        try:
            condition = json.loads(condition)
        except (json.JSONDecodeError, TypeError):
            return
    if not isinstance(condition, dict):
        return

    rule_type = rule.get("rule_type")

    if rule_type == "list":
        yield "condition", condition

    if rule_type == "attack_chain":
        steps = condition.get("ordered_steps")
        if isinstance(steps, list):
            for idx, step in enumerate(steps):
                if not isinstance(step, dict):
                    continue
                match = step.get("match")
                if isinstance(match, dict) and match.get("type") == "list":
                    yield f"condition.ordered_steps[{idx}].match", match

    # composite 的 sub_rules 中也可能嵌套 list 条件
    if rule_type == "composite":
        subs = condition.get("sub_rules")
        if isinstance(subs, list):
            for idx, sub in enumerate(subs):
                if isinstance(sub, dict) and sub.get("type") == "list":
                    yield f"condition.sub_rules[{idx}]", sub


def scan_ioc_dependent_rules(rules: Optional[list] = None,
                             inventory: Optional[dict] = None) -> dict:
    """扫描依赖动态 IOC 情报的规则，并对照当前情报库存量给出满足情况.

    Args:
        rules: 规则列表；None 时从 DB 读取全部启用规则。
        inventory: 情报存量 ``{ioc_type: count}``；None 时从 iocs 表实时统计。
            显式传入可用于测试或"假设情报库为空"的推演。

    Returns:
        ::

            {
              "ioc_inventory": {"ip": 12, "domain": 3, ...},
              "total_ioc_count": 15,
              "dependent_rules": [
                {"name": "suspicious_c2_domain", "rule_type": "list",
                 "path": "condition", "field": "remote_address",
                 "ioc_types": ["domain", "ip"], "static_values": 0,
                 "satisfied": true, "available": {"domain": 3, "ip": 12}}
              ],
              "unsatisfied_count": 0
            }
    """
    from app.rules.rule_engine import resolve_ioc_types

    # ── 1. 统计情报库存量 ────────────────────────────────
    if inventory is None:
        inventory = {}
        try:
            from app.models.ioc import Ioc
            for row in Ioc.list():
                if not row.get("enabled"):
                    continue
                t = row.get("ioc_type")
                if t:
                    inventory[t] = inventory.get(t, 0) + 1
        except Exception as exc:  # noqa: BLE001
            logger.debug("读取 iocs 表失败，按空情报库处理: %s", exc)

    # ── 2. 取规则集 ─────────────────────────────────────
    if rules is None:
        rules = []
        try:
            from app.models.rule import Rule
            rules = Rule.list(enabled=True)
        except Exception as exc:  # noqa: BLE001
            logger.debug("读取 rules 表失败，回退内置规则: %s", exc)
            try:
                from app.rules.loader import load_default_rules
                rules = [r for r in load_default_rules() if r.get("enabled", True)]
            except Exception as exc2:  # noqa: BLE001
                logger.warning("内置规则加载亦失败: %s", exc2)
                rules = []

    # ── 3. 逐条判定 ─────────────────────────────────────
    dependent: list = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        for path, cond in _iter_list_conditions(rule):
            field = cond.get("field", "")
            ioc_types = resolve_ioc_types(field, cond)
            if not ioc_types:
                continue
            static_values = cond.get("values") or []
            if not isinstance(static_values, list):
                static_values = [static_values]
            available = {t: inventory.get(t, 0) for t in ioc_types}
            has_dynamic = any(v > 0 for v in available.values())
            # 满足条件：有静态值兜底，或情报库中至少有一类可用指标
            satisfied = bool(static_values) or has_dynamic
            dependent.append({
                "name": rule.get("name"),
                "label": rule.get("label"),
                "rule_type": rule.get("rule_type"),
                "severity": rule.get("severity"),
                "path": path,
                "field": field,
                "ioc_types": ioc_types,
                "static_values": len(static_values),
                "available": available,
                "satisfied": satisfied,
                "requires_ioc": bool((cond.get("_meta") or {}).get("requires_ioc")),
            })

    unsatisfied = [d for d in dependent if not d["satisfied"]]
    return {
        "ioc_inventory": inventory,
        "total_ioc_count": sum(inventory.values()),
        "dependent_rules": dependent,
        "dependent_count": len(dependent),
        "unsatisfied_count": len(unsatisfied),
        "unsatisfied_rules": [d["name"] for d in unsatisfied],
    }
