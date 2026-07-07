"""持久化痕迹查找器 — 汇总和评估持久化痕迹."""

import logging
from typing import Any

from app.rules.rule_engine import RuleEngine

logger = logging.getLogger(__name__)


class PersistenceFinder:
    """持久化痕迹查找器."""

    @staticmethod
    def find_all(raw_data: dict) -> list:
        """汇总所有持久化痕迹.

        Args:
            raw_data: Agent JSON 数据.

        Returns:
            持久化痕迹列表.
        """
        items = []

        # 从 persistence 采集器结果获取
        persistence = raw_data.get("persistence", {})
        if isinstance(persistence, dict):
            type_mapping = {
                "run_keys": "run_key",
                "scheduled_tasks": "scheduled_task",
                "services": "service",
                "startup_folder": "startup_folder",
                "wmi_subscriptions": "wmi",
                "cron_jobs": "cron",
                "systemd_units": "systemd",
                "rc_local": "rc_local",
            }

            for key, ptype in type_mapping.items():
                entries = persistence.get(key, [])
                if isinstance(entries, list):
                    for entry in entries:
                        if isinstance(entry, dict):
                            items.append({
                                "type": ptype,
                                "name": entry.get("name", ""),
                                "command": entry.get("command", ""),
                                "location": entry.get("location", ""),
                                "user": entry.get("user", ""),
                                "is_suspicious": False,
                                "reason": "",
                                "details": entry,
                            })

        # 从 startup_items 获取
        startup_items = raw_data.get("startup_items", [])
        if isinstance(startup_items, list):
            for item in startup_items:
                if isinstance(item, dict):
                    items.append({
                        "type": item.get("type", "unknown"),
                        "name": item.get("name", ""),
                        "command": item.get("command", ""),
                        "location": item.get("location", ""),
                        "user": item.get("user", ""),
                        "is_suspicious": False,
                        "reason": "",
                        "details": item,
                    })

        # 从 registry 获取
        registry = raw_data.get("registry", {})
        if isinstance(registry, dict):
            run_keys = registry.get("run_keys", [])
            if isinstance(run_keys, list):
                for entry in run_keys:
                    if isinstance(entry, dict):
                        items.append({
                            "type": "run_key",
                            "name": entry.get("name", ""),
                            "command": entry.get("value", ""),
                            "location": entry.get("key", ""),
                            "user": "all",
                            "is_suspicious": False,
                            "reason": "",
                            "details": entry,
                        })

        return items

    @staticmethod
    def assess_suspicious(items: list, rules: list) -> list:
        """评估每项是否可疑，标注原因.

        Args:
            items: 持久化痕迹列表.
            rules: 规则列表.

        Returns:
            评估后的持久化痕迹列表（含 is_suspicious 和 reason）.
        """
        # 筛选持久化和启动项规则
        persistence_rules = [r for r in rules if r.get("category") in ("persistence", "startup")]

        matches = RuleEngine.evaluate(items, persistence_rules)

        # 构建匹配索引
        match_map: dict[int, list] = {}
        for i, match in enumerate(matches):
            item = match["item"]
            # 用 name+command+location 作为唯一标识
            key = f"{item.get('name', '')}|{item.get('command', '')}|{item.get('location', '')}"
            if key not in match_map:
                match_map[key] = []
            match_map[key].append(match)

        # 标注可疑项
        assessed = []
        for item in items:
            key = f"{item.get('name', '')}|{item.get('command', '')}|{item.get('location', '')}"
            if key in match_map:
                item_matches = match_map[key]
                # 取最严重的
                severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
                best_match = min(item_matches, key=lambda m: severity_order.get(m["severity"], 4))
                item["is_suspicious"] = True
                item["reason"] = best_match["reason"]
                item["severity"] = best_match["severity"]
            else:
                # 检查 WMI 订阅等高危类型
                if item.get("type") == "wmi":
                    item["is_suspicious"] = True
                    item["reason"] = "WMI 事件订阅是高级持久化技术"
                    item["severity"] = "critical"
                else:
                    item["is_suspicious"] = False
                    item["reason"] = ""
                    item["severity"] = "info"
            assessed.append(item)

        return assessed
