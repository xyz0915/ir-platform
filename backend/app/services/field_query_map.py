"""字段 → 查询目标三级映射表（P0-3 / P0-1 共用）。

一级：security_events 真实列（含 hosts 联表列）
二级：evidence JSON 路径（JSON_EXTRACT 参数化）
三级：keyword 兜底（evidence/matched_rules/event_type LIKE）

操作符白名单与 ``nl_query_guard.ALLOWED_OPS`` 对齐：``= != contains in >= <= > <``
（``between`` 由 DSL 层展开为 ``>=`` + ``<=`` 两个条件）。

安全红线：字段名只从映射表常量取；值一律 ``?`` 绑定；绝不拼接用户输入。
"""

from __future__ import annotations

from typing import Any, Optional

# ── 一级：security_events 真实列（含 hosts 联表列）──────────────
COLUMN_FIELDS: dict[str, str] = {
    "host_id": "se.host_id",
    "hostname": "h.hostname",
    "event_type": "se.event_type",
    "severity": "se.severity",
    "timestamp": "se.timestamp",
    "attack_stage": "se.attack_stage",
    "source_collector": "se.source_collector",
    "status": "se.status",
    "ioc_matches": "se.ioc_matches",
    "assignee": "se.assignee",
    "event_key": "se.event_key",
    "attack_chain_id": "se.attack_chain_id",
}

# ── 二级：evidence JSON 路径（JSON_EXTRACT 参数化）─────────────
EVIDENCE_JSON_FIELDS: dict[str, str] = {
    "source_ip": "$.source_ip",
    "source_hostname": "$.source_hostname",
    "target_ip": "$.target_ip",
    "target_hostname": "$.target_hostname",
    "user_name": "$.user_name",
    "user_domain": "$.user_domain",
    "logon_session": "$.logon_session",
    "process_name": "$.process_name",
    "parent_process_name": "$.parent_process_name",
    "command_line": "$.command_line",
    "object_name": "$.object_name",
    "tags": "$.tags",
    "description": "$.description",
    "event_label": "$.event_label",
    "mitre_attack": "$.mitre_attack",
}

# ── 三级：keyword 兜底（evidence/matched_rules/event_type LIKE）──
KEYWORD_FALLBACK_FIELDS: set[str] = {"summary", "log_source", "ioc"}

# 操作符白名单（与 nl_query_guard.ALLOWED_OPS 对齐；between 由 DSL 展开）
ALLOWED_OPS = {"=", "!=", "contains", "in", ">=", "<=", ">", "<"}


def resolve_field(field: str) -> tuple[str, str]:
    """解析字段 → (kind, target).

    Args:
        field: 逻辑字段名。

    Returns:
        (kind, target)：
        - ("column", SQL列表达式)
        - ("json", JSON路径)
        - ("keyword", "")
        - ("unknown", field)
    """
    if field in COLUMN_FIELDS:
        return "column", COLUMN_FIELDS[field]
    if field in EVIDENCE_JSON_FIELDS:
        return "json", EVIDENCE_JSON_FIELDS[field]
    if field in KEYWORD_FALLBACK_FIELDS:
        return "keyword", ""
    return "unknown", field


def _leaf_sql(cond: dict, table_alias: str) -> tuple[str, list[Any]]:
    """单条件 → (SQL片段, 参数列表)。字段白名单 + 参数绑定，防注入硬红线。

    Raises:
        ValueError: 字段不在白名单、操作符非法或值类型错误（端点层转 400）。
    """
    field = cond.get("field")
    op = cond.get("op")
    value = cond.get("value")
    if not field:
        raise ValueError("条件缺少 field")
    # keyword 虚拟字段（DSL 裸词 / NL 兜底）：evidence/matched_rules/event_type LIKE
    if field == "keyword":
        if op not in ALLOWED_OPS:
            raise ValueError(f"操作符 {op!r} 不被允许")
        kw = f"%{value}%"
        return (
            f"({table_alias}.evidence LIKE ? OR {table_alias}.matched_rules LIKE ? "
            f"OR {table_alias}.event_type LIKE ?)",
            [kw, kw, kw],
        )
    kind, target = resolve_field(field)
    if kind == "unknown":
        raise ValueError(f"字段 {field!r} 不在白名单")
    if op not in ALLOWED_OPS:
        raise ValueError(f"操作符 {op!r} 不被允许")

    if kind == "column":
        expr = target
        params0: list[Any] = []
    elif kind == "json":
        expr = f"json_extract({table_alias}.evidence, ?)"
        params0 = [target]
    else:  # keyword 兜底：evidence / matched_rules / event_type LIKE
        kw = f"%{value}%"
        return (
            f"({table_alias}.evidence LIKE ? OR {table_alias}.matched_rules LIKE ? "
            f"OR {table_alias}.event_type LIKE ?)",
            [kw, kw, kw],
        )

    if op == "contains":
        return f"{expr} LIKE ?", params0 + [f"%{value}%"]
    if op == "in":
        vals = value if isinstance(value, list) else [value]
        if not vals:
            raise ValueError(f"字段 {field!r} 的 in 值不能为空")
        placeholders = ",".join("?" for _ in vals)
        return f"{expr} IN ({placeholders})", params0 + [str(v) for v in vals]
    sql_op = "=" if op == "=" else op
    return f"{expr} {sql_op} ?", params0 + [value]


def _tree_sql(node: Any, table_alias: str) -> tuple[str, list[Any]]:
    """逻辑树节点 → (SQL片段, 参数列表)。

    node 支持两种形态：
    - 叶子：{"field", "op", "value"}
    - 逻辑节点：{"logic": "and"|"or"|"not", "children": [...]} 或
      {"logic": "not", "child": {...}}
    """
    if isinstance(node, dict) and node.get("logic"):
        logic = node.get("logic")
        if logic == "not":
            child = node.get("child") or (node.get("children") or [None])[0]
            sql, params = _tree_sql(child, table_alias)
            if not sql:
                return "", []
            return f"(NOT ({sql}))", params
        children = node.get("children") or []
        parts: list[str] = []
        params: list[Any] = []
        for ch in children:
            sql, p = _tree_sql(ch, table_alias)
            if sql:
                parts.append(f"({sql})")
                params.extend(p)
        if not parts:
            return "", []
        joiner = " AND " if logic == "and" else " OR "
        return joiner.join(parts), params
    return _leaf_sql(node, table_alias)


def build_where_clause(
    field_conditions: Optional[list[dict]],
    table_alias: str = "se",
) -> tuple[str, list[Any]]:
    """将结构化 field_conditions 编译为参数化 SQL 子句（防注入硬红线）.

    Args:
        field_conditions: [{"field", "op", "value"}, ...]（AND 语义；
            元素可为逻辑树节点 {"logic", "children"}，支持 DSL OR/NOT）。
        table_alias: 主表别名（默认 se，用于 json_extract 参数化）。

    Returns:
        (where_clause, params)。无条件时 where_clause=''。

    Raises:
        ValueError: 字段不在白名单、操作符非法或值类型错误（端点层转 400）。
    """
    if not field_conditions:
        return "", []
    clauses: list[str] = []
    params: list[Any] = []
    for cond in field_conditions:
        sql, p = _tree_sql(cond, table_alias)
        if sql:
            clauses.append(f"({sql})")
            params.extend(p)
    return " AND ".join(clauses), params
