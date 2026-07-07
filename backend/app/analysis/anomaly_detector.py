"""异常检测器 — 检测异常进程、可疑外连、可疑启动项."""

import logging
from typing import Any

from app.rules.rule_engine import RuleEngine

logger = logging.getLogger(__name__)


class AnomalyDetector:
    """异常检测器.

    通过规则引擎检测进程、网络连接、启动项中的异常.
    """

    @staticmethod
    def detect_processes(raw_data: dict, rules: list) -> list:
        """检测异常进程.

        Args:
            raw_data: Agent JSON 数据.
            rules: 规则列表.

        Returns:
            异常进程列表.
        """
        processes = raw_data.get("processes", [])
        if not isinstance(processes, list):
            return []

        # 筛选进程相关规则
        process_rules = [r for r in rules if r.get("category") in ("process", "behavior")]
        behavior_rules = [r for r in rules if r.get("category") == "behavior"]

        # 为每个进程补充 parent_name 和 connection_count
        pid_to_name = {p.get("pid"): p.get("name", "") for p in processes if isinstance(p, dict)}
        for proc in processes:
            if isinstance(proc, dict):
                ppid = proc.get("ppid", 0)
                proc["parent_name"] = pid_to_name.get(ppid, "")
                connections = proc.get("connections", [])
                proc["connection_count"] = len(connections) if isinstance(connections, list) else 0

        matches = RuleEngine.evaluate(processes, process_rules + behavior_rules)

        abnormal_processes = []
        for match in matches:
            item = match["item"]
            abnormal_processes.append({
                "pid": item.get("pid"),
                "process_name": item.get("name", ""),
                "process_path": item.get("path", ""),
                "command_line": item.get("command_line", ""),
                "parent_pid": item.get("ppid"),
                "parent_name": item.get("parent_name", ""),
                "reason": match["reason"],
                "rule_name": match["rule_name"],
                "severity": match["severity"],
                "details": {
                    "user": item.get("user", ""),
                    "start_time": item.get("start_time", ""),
                    "threads": item.get("threads", 0),
                },
            })

        # 去重（同一 PID 可能命中多条规则，保留最严重的）
        seen_pids: dict[int, dict] = {}
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
        for proc in abnormal_processes:
            pid = proc.get("pid", 0)
            if pid not in seen_pids:
                seen_pids[pid] = proc
            else:
                existing_sev = severity_order.get(seen_pids[pid].get("severity", "info"), 4)
                new_sev = severity_order.get(proc.get("severity", "info"), 4)
                if new_sev < existing_sev:
                    seen_pids[pid] = proc

        return list(seen_pids.values())

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
