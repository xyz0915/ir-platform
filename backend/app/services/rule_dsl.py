"""规则 DSL 安全校验器（P0-B）.

确保 AI 生成的规则满足三条安全红线：

1. **绝不执行任意代码**：condition 只能是数据对象，禁止 ``eval`` / ``exec`` /
   动态导入等结构，引擎也仅以白名单字段与运算符做匹配，不会执行表达式。
2. **拒绝笛卡尔积 / 全表扫描**：限制 list 取值数量、composite 子规则数量与
   嵌套深度；拒绝 ``regex`` 匹配全部（``.*``）这类全表扫描模式。
3. **拒绝内嵌 DDL / SQL 注入**：扫描所有字符串，命中 ``DROP`` / ``SELECT`` /
   ``UNION`` 等关键字或 ``;`` / ``--`` 即拒绝。
"""

import logging
import re
from typing import Any, Dict, Tuple

logger = logging.getLogger(__name__)

# 归一化日志 / 事件项可用字段白名单
ALLOWED_FIELDS = {
    "event_type",
    "event_label",
    "log_source",
    "severity",
    "mitre_attack",
    "source_ip",
    "source_hostname",
    "target_ip",
    "target_hostname",
    "user_name",
    "user_domain",
    "logon_session",
    "process_name",
    "process_pid",
    "parent_process_name",
    "parent_process_pid",
    "command_line",
    "object_name",
    "hostname",
    "host_id",
    "tags",
    "description",
    "timestamp",
    "start_time",
    "end_time",
    "count",
    "value",
    "field",
}

# condition 允许的键白名单（递归校验 sub_rules）
ALLOWED_KEYS = {
    "type",
    "field",
    "pattern",
    "patterns",
    "values",
    "value",
    "match_mode",
    "operator",
    "logic",
    "sub_rules",
    "steps",
    "min_chain_length",
    "suspicious_process_patterns",
    "suspicious_cmdline_patterns",
    "suspicious_path_patterns",
    "window_minutes",
    "threshold_field",
    "threshold_value",
    "comparison",
    "case_sensitive",
}

# 白名单运算符
ALLOWED_OPERATORS = {
    "==",
    "!=",
    ">",
    ">=",
    "<",
    "<=",
    "contains",
    "icontains",
    "in",
    "not_in",
    "regex",
    "startswith",
    "endswith",
    "eq",
    "ne",
}

# 危险 DDL / SQL 结构（命中即拒绝）
DANGEROUS_SQL = re.compile(
    r"\b(DROP|CREATE\s+TABLE|ALTER\s+TABLE|TRUNCATE|DELETE\s+FROM|INSERT\s+INTO|"
    r"UPDATE\s+\w+\s+SET|SELECT\s+\*?\s+FROM|UNION\s+SELECT|EXEC|EXECUTE|"
    r"PRAGMA|ATTACH)\b|;|--",
    re.IGNORECASE,
)

# 危险的代码执行结构（杜绝代码注入）
DANGEROUS_CODE = re.compile(
    r"\b(eval|exec|compile|__import__|import\s+os|subprocess|os\.system|"
    r"open\(|socket\.|pickle|marshal|yaml\.load|getattr|setattr|"
    r"__globals__|__builtins__|chr\(|ord\()\b"
)

# 阈值：防止笛卡尔积 / 全表扫描
MAX_LIST_VALUES = 1000
MAX_SUB_RULES = 50
MAX_NEST_DEPTH = 3


class RuleDSL:
    """规则 DSL 安全校验器（静态方法集合）."""

    @staticmethod
    def validate(rule_type: str, condition: Any) -> Tuple[bool, str]:
        """校验规则 condition 的安全性与可计算性.

        Args:
            rule_type: 规则类型（须为白名单之一）.
            condition: 规则条件对象.

        Returns:
            (ok, error): 校验通过时 error 为空串；否则 error 描述拒绝原因.
        """
        if rule_type not in {
            "regex",
            "list",
            "threshold",
            "behavior",
            "composite",
            "exists",
            "attack_chain",
        }:
            return False, f"不支持的 rule_type: {rule_type}"
        if not isinstance(condition, dict):
            return False, "condition 必须是 JSON 对象（禁止任意代码）"
        ok, err = RuleDSL._scan_strings(condition)
        if not ok:
            return False, err
        ok, err = RuleDSL._check_keys(condition)
        if not ok:
            return False, err
        ok, err = RuleDSL._check_structure(rule_type, condition, depth=0)
        if not ok:
            return False, err
        return True, ""

    @staticmethod
    def _scan_strings(node: Any) -> Tuple[bool, str]:
        """递归扫描所有字符串，拒绝 DDL / 代码注入."""
        if isinstance(node, str):
            if DANGEROUS_SQL.search(node):
                return False, "condition 含禁止的 DDL/SQL 结构"
            if DANGEROUS_CODE.search(node):
                return False, "condition 含禁止的代码执行结构（eval/exec/...）"
            return True, ""
        if isinstance(node, dict):
            for v in node.values():
                ok, err = RuleDSL._scan_strings(v)
                if not ok:
                    return False, err
        elif isinstance(node, list):
            for v in node:
                ok, err = RuleDSL._scan_strings(v)
                if not ok:
                    return False, err
        return True, ""

    @staticmethod
    def _check_keys(condition: dict) -> Tuple[bool, str]:
        """校验 condition 顶层键是否在白名单内."""
        for k in condition.keys():
            if k not in ALLOWED_KEYS and not k.startswith("_"):
                return False, f"condition 含非白名单键: {k}"
        return True, ""

    @staticmethod
    def _check_structure(
        rule_type: str, condition: dict, depth: int
    ) -> Tuple[bool, str]:
        """按规则类型做结构与阈值校验（递归处理 composite）."""
        if depth > MAX_NEST_DEPTH:
            return False, f"condition 嵌套超过 {MAX_NEST_DEPTH} 层（疑似笛卡尔积）"

        if rule_type == "regex":
            pat = condition.get("pattern", "")
            if pat in ("", ".*", ".+", "^.*$", ".*.*"):
                return False, "regex 模式为空或匹配全部，疑似全表扫描"

        elif rule_type == "list":
            vals = condition.get("values") or []
            if not isinstance(vals, list) or len(vals) == 0:
                return False, "list 规则 values 必须非空数组"
            if len(vals) > MAX_LIST_VALUES:
                return False, f"list 规则 values 超过 {MAX_LIST_VALUES}（笛卡尔积风险）"
            fld = condition.get("field")
            if fld and fld not in ALLOWED_FIELDS:
                return False, f"list 引用非白名单字段: {fld}"

        elif rule_type == "threshold":
            fld = condition.get("field") or condition.get("threshold_field")
            op = condition.get("operator") or condition.get("comparison")
            if fld and fld not in ALLOWED_FIELDS:
                return False, f"threshold 引用非白名单字段: {fld}"
            if op and op not in ALLOWED_OPERATORS:
                return False, f"threshold 运算符非法: {op}"

        elif rule_type == "exists":
            fld = condition.get("field")
            if fld and fld not in ALLOWED_FIELDS:
                return False, f"exists 引用非白名单字段: {fld}"

        elif rule_type == "behavior":
            pat = condition.get("pattern", "")
            if pat and not isinstance(pat, str):
                return False, "behavior pattern 必须为字符串"

        elif rule_type == "composite":
            subs = condition.get("sub_rules") or []
            if not isinstance(subs, list) or len(subs) == 0:
                return False, "composite 规则 sub_rules 必须非空数组"
            if len(subs) > MAX_SUB_RULES:
                return False, f"composite sub_rules 超过 {MAX_SUB_RULES}（笛卡尔积风险）"
            logic = condition.get("logic", "and")
            if logic not in ("and", "or", "not"):
                return False, f"composite logic 非法: {logic}"
            for sub in subs:
                if not isinstance(sub, dict):
                    return False, "sub_rules 元素必须为对象"
                ok, err = RuleDSL._check_keys(sub)
                if not ok:
                    return False, err
                ok, err = RuleDSL._check_structure(
                    sub.get("type", "regex"), sub, depth + 1
                )
                if not ok:
                    return False, err

        elif rule_type == "attack_chain":
            steps = condition.get("steps") or []
            if len(steps) > MAX_SUB_RULES:
                return False, f"attack_chain steps 超过 {MAX_SUB_RULES}"

        return True, ""
