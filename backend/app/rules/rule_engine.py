"""规则引擎核心 — 支持 regex/list/threshold/behavior 四种规则类型."""

import json
import logging
import re
from typing import Any, Optional

from app.models.rule import Rule

logger = logging.getLogger(__name__)


class RuleEngine:
    """规则引擎.

    支持四种规则类型：regex、list、threshold、behavior.
    """

    @staticmethod
    def load_rules(category: Optional[str] = None) -> list:
        """从数据库加载启用的规则.

        Args:
            category: 规则类别过滤（可选）.

        Returns:
            规则列表.
        """
        if category:
            return Rule.list(category=category, enabled=True)
        return Rule.list_enabled()

    @staticmethod
    def evaluate(data_items: list, rules: list) -> list:
        """对数据项列表执行规则匹配.

        Args:
            data_items: 待检测的数据项列表.
            rules: 规则列表.

        Returns:
            匹配结果列表 [{item, rule, reason}].
        """
        matches = []
        for item in data_items:
            if not isinstance(item, dict):
                continue
            for rule in rules:
                if RuleEngine.match_rule(item, rule):
                    matches.append({
                        "item": item,
                        "rule": rule,
                        "rule_name": rule.get("name", ""),
                        "severity": rule.get("severity", "medium"),
                        "reason": RuleEngine._build_reason(item, rule),
                    })
        return matches

    @staticmethod
    def match_rule(data_item: dict, rule: dict) -> bool:
        """检查单个数据项是否匹配规则.

        Args:
            data_item: 数据项字典.
            rule: 规则字典.

        Returns:
            是否匹配.
        """
        rule_type = rule.get("rule_type", "")
        condition = rule.get("condition", {})
        if isinstance(condition, str):
            try:
                condition = json.loads(condition)
            except json.JSONDecodeError:
                return False

        if rule_type == "regex":
            return RuleEngine._match_regex(data_item, condition)
        elif rule_type == "list":
            return RuleEngine._match_list(data_item, condition)
        elif rule_type == "threshold":
            return RuleEngine._match_threshold(data_item, condition)
        elif rule_type == "behavior":
            return RuleEngine._match_behavior(data_item, condition)
        return False

    @staticmethod
    def _match_regex(data_item: dict, condition: dict) -> bool:
        """正则匹配.

        Condition 格式: {"field": "command_line", "pattern": "powershell.*-enc", "flags": "ignorecase"}
        """
        field = condition.get("field", "")
        pattern = condition.get("pattern", "")
        flags_str = condition.get("flags", "")

        value = str(data_item.get(field, ""))
        if not value or not pattern:
            return False

        flags = 0
        if "ignorecase" in flags_str:
            flags |= re.IGNORECASE
        if "multiline" in flags_str:
            flags |= re.MULTILINE

        try:
            return bool(re.search(pattern, value, flags))
        except re.error:
            return False

    @staticmethod
    def _match_list(data_item: dict, condition: dict) -> bool:
        """黑名单匹配.

        Condition 格式: {"field": "remote_address", "values": ["1.2.3.4", "5.6.7.8"], "match_mode": "exact"}
        """
        field = condition.get("field", "")
        values = condition.get("values", [])
        match_mode = condition.get("match_mode", "exact")

        value = data_item.get(field, "")
        if not value or not values:
            return False

        value_str = str(value).lower()
        for v in values:
            v_str = str(v).lower()
            if match_mode == "exact":
                if value_str == v_str:
                    return True
            elif match_mode == "contains":
                if v_str in value_str:
                    return True
            elif match_mode == "startswith":
                if value_str.startswith(v_str):
                    return True
        return False

    @staticmethod
    def _match_threshold(data_item: dict, condition: dict) -> bool:
        """阈值检测.

        Condition 格式: {"field": "connection_count", "operator": ">", "value": 50}
        """
        field = condition.get("field", "")
        operator = condition.get("operator", ">")
        threshold_value = condition.get("value", 0)

        value = data_item.get(field, 0)
        try:
            value = float(value)
        except (ValueError, TypeError):
            return False

        if operator == ">":
            return value > threshold_value
        elif operator == ">=":
            return value >= threshold_value
        elif operator == "<":
            return value < threshold_value
        elif operator == "<=":
            return value <= threshold_value
        elif operator == "==":
            return value == threshold_value
        elif operator == "!=":
            return value != threshold_value
        return False

    @staticmethod
    def _match_behavior(data_item: dict, condition: dict) -> bool:
        """行为模式检测.

        Condition 格式: {"pattern": "orphan_process", "description": "..."}
        """
        pattern = condition.get("pattern", "")

        if pattern == "orphan_process":
            # 无父进程或父进程已退出
            ppid = data_item.get("ppid", 0)
            return ppid == 0 or ppid is None
        elif pattern == "suspicious_parent":
            # 可疑父进程（如 word 启动 powershell）
            parent_name = str(data_item.get("parent_name", "")).lower()
            child_name = str(data_item.get("name", "")).lower()
            suspicious_parents = ["winword.exe", "excel.exe", "powerpnt.exe", "outlook.exe"]
            suspicious_children = ["powershell.exe", "cmd.exe", "wscript.exe", "cscript.exe"]
            return parent_name in suspicious_parents and child_name in suspicious_children
        elif pattern == "unsigned_process":
            # 无签名进程（简化版：检查路径不在系统目录）
            path = str(data_item.get("path", "")).lower()
            system_dirs = ["c:\\windows\\system32", "c:\\windows\\syswow64", "/usr/bin", "/usr/sbin"]
            return path and not any(d in path for d in system_dirs)
        elif pattern == "network_scan":
            # 网络扫描行为（大量连接到不同 IP）
            connections = data_item.get("connections", [])
            if isinstance(connections, list):
                unique_ips = set()
                for conn in connections:
                    remote = conn.get("remote_address", "")
                    if remote:
                        unique_ips.add(remote)
                return len(unique_ips) > 20
        return False

    @staticmethod
    def _build_reason(data_item: dict, rule: dict) -> str:
        """构建规则命中原因说明."""
        rule_name = rule.get("name", "")
        description = rule.get("description", "")
        condition = rule.get("condition", {})
        if isinstance(condition, str):
            try:
                condition = json.loads(condition)
            except json.JSONDecodeError:
                condition = {}

        field = condition.get("field", "")
        value = data_item.get(field, "")
        if value:
            return f"规则 '{rule_name}' 命中: 字段 '{field}' 值 '{str(value)[:100]}' — {description}"
        return f"规则 '{rule_name}' 命中 — {description}"
