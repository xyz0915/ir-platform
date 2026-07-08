"""异常检测器 — 检测异常进程、可疑外连、可疑启动项（增强版含白名单过滤+累加评分+进程链检测）."""

import json
import logging
from typing import Any, Optional

from app.rules.rule_engine import RuleEngine

logger = logging.getLogger(__name__)

# 累加评分权重映射
SEVERITY_SCORES: dict[str, int] = {
    "critical": 40,
    "high": 25,
    "medium": 10,
    "low": 5,
    "info": 2,
}

# 严重程度优先级排序
SEVERITY_ORDER: dict[str, int] = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
    "info": 4,
}


class AnomalyDetector:
    """异常检测器（增强版）.

    通过规则引擎检测进程、网络连接、启动项中的异常。
    增强功能：
    - 白名单过滤：传入 whitelist_service 对象，过滤掉白名单进程
    - 全局上下文：构建 process_map 和 all_items，用于 process_chain/time_cluster 检测
    - 累加评分：同一 PID 合并所有命中规则，累加 risk_score，提取 attack_path
    """

    @staticmethod
    def detect_processes(raw_data: dict, rules: list, whitelist_service=None) -> list:
        """检测异常进程（增强版）.

        Args:
            raw_data: Agent JSON 数据.
            rules: 规则列表.
            whitelist_service: 白名单服务对象（可选），用于过滤白名单进程.

        Returns:
            异常进程列表（含 risk_score/matched_rules/attack_path 字段）.
        """
        processes = raw_data.get("processes", [])
        if not isinstance(processes, list):
            return []

        # ── 1. 白名单过滤 ─────────────────────────────────────────────
        if whitelist_service:
            processes = whitelist_service.filter_whitelisted(processes)
            logger.info("After whitelist filtering: %d processes remain", len(processes))

        # ── 2. 补充 parent_name 和 connection_count，构建 process_map ─
        pid_to_proc: dict[int, dict] = {}
        for proc in processes:
            if isinstance(proc, dict):
                pid = proc.get("pid")
                if pid is not None:
                    pid_to_proc[pid] = proc

        for proc in processes:
            if isinstance(proc, dict):
                ppid = proc.get("ppid", 0)
                parent_proc = pid_to_proc.get(ppid)
                proc["parent_name"] = parent_proc.get("name", "") if parent_proc else ""
                connections = proc.get("connections", [])
                proc["connection_count"] = len(connections) if isinstance(connections, list) else 0

        # ── 3. 规则匹配（含全局上下文）──────────────────────────────
        process_rules = [r for r in rules if r.get("category") in ("process", "behavior", "execution")]
        global_context = {
            "process_map": pid_to_proc,
            "all_items": processes,
        }

        matches = RuleEngine.evaluate(
            processes, process_rules, global_context=global_context
        )

        # ── 4. 累加评分合并 ──────────────────────────────────────────
        abnormal_processes = AnomalyDetector._apply_accumulated_scoring(matches)

        return abnormal_processes

    @staticmethod
    def _apply_accumulated_scoring(matches: list) -> list:
        """累加评分合并 — 同一 PID 合并所有命中规则，累加 risk_score.

        对每个 PID：
        - 合并所有 matched_rules（[{name, severity, reason}]）
        - 累加 risk_score：critical=40, high=25, medium=10, low=5, info=2
        - risk_score = min(sum, 100)
        - severity 取所有命中规则中最高的
        - attack_path 从 process_chain 命中中提取

        Args:
            matches: 规则匹配结果列表.

        Returns:
            增强版异常进程列表（含 risk_score/matched_rules/attack_path）.
        """
        # 按 PID 聚合所有命中规则
        pid_groups: dict[int, list] = {}
        for match in matches:
            item = match.get("item", {})
            pid = item.get("pid", 0)
            if pid not in pid_groups:
                pid_groups[pid] = []
            pid_groups[pid].append(match)

        abnormal_processes = []
        for pid, group_matches in pid_groups.items():
            # 取第一个 match 的 item 作为基础
            base_item = group_matches[0]["item"]

            # 合并所有命中规则
            matched_rules_list = []
            total_score = 0
            highest_severity = "info"
            highest_severity_order = SEVERITY_ORDER.get("info", 4)
            attack_path = None

            for m in group_matches:
                rule_name = m.get("rule_name", "")
                severity = m.get("severity", "medium")
                reason = m.get("reason", "")

                matched_rules_list.append({
                    "name": rule_name,
                    "severity": severity,
                    "reason": reason,
                })

                # 累加评分
                total_score += SEVERITY_SCORES.get(severity, 2)

                # 取最高严重程度
                sev_order = SEVERITY_ORDER.get(severity, 4)
                if sev_order < highest_severity_order:
                    highest_severity = severity
                    highest_severity_order = sev_order

                # 提取 attack_path（从 process_chain 命中中）
                item_data = m.get("item", {})
                if item_data.get("_attack_path"):
                    attack_path = item_data["_attack_path"]

            # risk_score 上限 100
            risk_score = min(total_score, 100)

            # 如果没有 process_chain 命中但 PID 有父链信息，构建简单 attack_path
            if attack_path is None and base_item.get("parent_name"):
                attack_path = f"{base_item.get('parent_name', '')} → {base_item.get('name', '')}"

            abnormal_processes.append({
                "pid": base_item.get("pid"),
                "process_name": base_item.get("name", ""),
                "process_path": base_item.get("path", ""),
                "command_line": base_item.get("command_line", ""),
                "parent_pid": base_item.get("ppid"),
                "parent_name": base_item.get("parent_name", ""),
                "reason": group_matches[0].get("reason", ""),
                "rule_name": group_matches[0].get("rule_name", ""),
                "severity": highest_severity,
                "details": {
                    "user": base_item.get("user", ""),
                    "start_time": base_item.get("start_time", ""),
                    "threads": base_item.get("threads", 0),
                },
                "risk_score": risk_score,
                "matched_rules": matched_rules_list,
                "attack_path": attack_path,
            })

        return abnormal_processes

    @staticmethod
    def detect_connections(raw_data: dict, rules: list) -> list:
        """检测可疑外连.

        Args:
            raw_data: Agent JSON 数据.
            rules: 规则列表.

        Returns:
            可疑外连列表.
        """
        network = raw_data.get("network", {})
        if not isinstance(network, dict):
            return []

        connections = network.get("connections", [])
        if not isinstance(connections, list):
            return []

        # 筛选网络和 IOC 相关规则
        network_rules = [r for r in rules if r.get("category") in ("network", "ioc")]

        matches = RuleEngine.evaluate(connections, network_rules)

        suspicious_connections = []
        for match in matches:
            item = match["item"]
            suspicious_connections.append({
                "protocol": item.get("protocol", ""),
                "local_address": item.get("local_address", ""),
                "local_port": item.get("local_port", 0),
                "remote_address": item.get("remote_address", ""),
                "remote_port": item.get("remote_port", 0),
                "state": item.get("state", ""),
                "process_name": item.get("process_name", ""),
                "pid": item.get("pid", 0),
                "reason": match["reason"],
                "rule_name": match["rule_name"],
                "severity": match["severity"],
            })

        return suspicious_connections

    @staticmethod
    def detect_startup_items(raw_data: dict, rules: list) -> list:
        """检测可疑启动项.

        Args:
            raw_data: Agent JSON 数据.
            rules: 规则列表.

        Returns:
            可疑启动项列表.
        """
        startup_items = raw_data.get("startup_items", [])
        if not isinstance(startup_items, list):
            return []

        # 筛选启动项和持久化相关规则
        startup_rules = [r for r in rules if r.get("category") in ("startup", "persistence")]

        matches = RuleEngine.evaluate(startup_items, startup_rules)

        suspicious_items = []
        for match in matches:
            item = match["item"]
            suspicious_items.append({
                "name": item.get("name", ""),
                "command": item.get("command", ""),
                "location": item.get("location", ""),
                "type": item.get("type", ""),
                "user": item.get("user", ""),
                "reason": match["reason"],
                "rule_name": match["rule_name"],
                "severity": match["severity"],
            })

        return suspicious_items
