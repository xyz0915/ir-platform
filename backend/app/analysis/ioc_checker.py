"""IOC 检测器 — 在采集数据中搜索 IOC."""

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


class IocChecker:
    """IOC 检测器.

    在进程、网络连接、文件、注册表等数据源中匹配 IOC.
    """

    @staticmethod
    def check(raw_data: dict, ioc_rules: list) -> list:
        """在采集数据中搜索 IOC.

        Args:
            raw_data: Agent JSON 数据.
            ioc_rules: IOC 相关规则列表.

        Returns:
            IOC 命中列表.
        """
        hits = []

        # 从 Agent 自带的 IOC 扫描结果中获取
        agent_ioc = raw_data.get("ioc", {})
        if isinstance(agent_ioc, dict):
            matched_items = agent_ioc.get("matched_items", [])
            if isinstance(matched_items, list):
                for item in matched_items:
                    if isinstance(item, dict):
                        hits.append({
                            "ioc_type": item.get("ioc_type", "unknown"),
                            "ioc_value": item.get("ioc_value", ""),
                            "matched_in": item.get("matched_in", ""),
                            "context": item.get("context", ""),
                            "severity": item.get("severity", "high"),
                        })

        # 从规则引擎检测 IOC（网络连接中的恶意 IP/域名）
        from app.rules.rule_engine import RuleEngine

        network = raw_data.get("network", {})
        if isinstance(network, dict):
            connections = network.get("connections", [])
            if isinstance(connections, list):
                matches = RuleEngine.evaluate(connections, ioc_rules)
                for match in matches:
                    item = match["item"]
                    hits.append({
                        "ioc_type": "ip" if match["rule_name"].startswith("known_bad_ip") else "domain",
                        "ioc_value": item.get("remote_address", ""),
                        "matched_in": "network_connections",
                        "context": f"远程端口: {item.get('remote_port')}, 进程: {item.get('process_name', '')}",
                        "severity": match["severity"],
                    })

        # 检查进程命令行中的 IOC
        processes = raw_data.get("processes", [])
        if isinstance(processes, list):
            ioc_list_rules = [r for r in ioc_rules if r.get("rule_type") == "list"]
            matches = RuleEngine.evaluate(processes, ioc_list_rules)
            for match in matches:
                item = match["item"]
                condition = match["rule"].get("condition", {})
                if isinstance(condition, str):
                    import json
                    try:
                        condition = json.loads(condition)
                    except json.JSONDecodeError:
                        condition = {}
                field = condition.get("field", "")
                hits.append({
                    "ioc_type": "ip" if "address" in field else "domain",
                    "ioc_value": item.get(field, ""),
                    "matched_in": f"process:{item.get('name', '')}",
                    "context": f"PID: {item.get('pid')}, 命令行: {item.get('command_line', '')[:200]}",
                    "severity": match["severity"],
                })

        # 检查文件哈希
        files = raw_data.get("files", {})
        if isinstance(files, dict):
            suspicious_files = files.get("suspicious_files", [])
            if isinstance(suspicious_files, list):
                known_bad_hashes = []
                if isinstance(agent_ioc, dict):
                    known_bad_hashes = agent_ioc.get("known_bad_hashes", [])
                for file_info in suspicious_files:
                    if isinstance(file_info, dict):
                        for bad_hash in known_bad_hashes:
                            file_path = file_info.get("path", "")
                            if bad_hash and bad_hash in str(file_info):
                                hits.append({
                                    "ioc_type": "hash",
                                    "ioc_value": bad_hash,
                                    "matched_in": "file",
                                    "context": file_path,
                                    "severity": "critical",
                                })

        # 融合扩充：WebShell 文件哈希纳入 known_bad_hashes 供给（A §二/§四）
        # 不破坏现有 files.suspicious_files 逻辑；独立扫描 webshells[].sha256。
        webshells = raw_data.get("webshells")
        if isinstance(webshells, list) and isinstance(agent_ioc, dict):
            known_bad_hashes = agent_ioc.get("known_bad_hashes", []) or []
            for ws in webshells:
                if not isinstance(ws, dict):
                    continue
                ws_hash = ws.get("sha256")
                if not ws_hash:
                    continue
                for bad_hash in known_bad_hashes:
                    if bad_hash and str(ws_hash).lower() == str(bad_hash).lower():
                        hits.append({
                            "ioc_type": "hash",
                            "ioc_value": bad_hash,
                            "matched_in": "webshell",
                            "context": ws.get("path", "") or ws.get("name", ""),
                            "severity": "critical",
                        })
                        break

        # 去重
        seen = set()
        unique_hits = []
        for hit in hits:
            key = f"{hit.get('ioc_type')}:{hit.get('ioc_value')}:{hit.get('matched_in')}"
            if key not in seen:
                seen.add(key)
                unique_hits.append(hit)

        return unique_hits
