"""16. 时间线构建采集器."""

import logging
from datetime import datetime
from typing import Any

from collectors.base_collector import BaseCollector

logger = logging.getLogger(__name__)


class TimelineCollector(BaseCollector):
    """时间线构建采集器.

    从各采集器结果中提取时间戳，构建统一时间线.
    """

    name = "timeline"
    platform = ["windows", "linux"]

    def collect(self) -> list:
        """构建时间线（需要在所有其他采集器完成后调用）."""
        # 此采集器在 agent.py 中最后执行，通过访问之前采集器的结果来构建时间线
        # 但由于独立执行模式，这里返回空列表，实际时间线由 agent.py 的 build_output 处理
        return []

    def build_from_results(self, all_results: dict) -> list:
        """从所有采集器结果中构建时间线.

        Args:
            all_results: 所有采集器的结果字典.

        Returns:
            排序后的时间线事件列表.
        """
        events = []

        # 从进程信息提取
        events.extend(self._extract_from_processes(all_results.get("processes", [])))

        # 从网络连接提取
        events.extend(self._extract_from_network(all_results.get("network", {})))

        # 从日志提取
        events.extend(self._extract_from_logs(all_results.get("logs", {})))

        # 从文件提取
        events.extend(self._extract_from_files(all_results.get("files", {})))

        # 从浏览器历史提取
        events.extend(self._extract_from_browser(all_results.get("browser", {})))

        # 从安全事件提取
        events.extend(self._extract_from_security(all_results.get("security", {})))

        # 按时间排序
        events.sort(key=lambda e: e.get("timestamp", ""))

        return events

    def _extract_from_processes(self, processes: list) -> list:
        """从进程信息提取时间线事件."""
        events = []
        for proc in processes:
            start_time = proc.get("start_time")
            if start_time:
                events.append({
                    "timestamp": start_time,
                    "event_type": "process",
                    "source": "processes",
                    "description": f"进程启动: {proc.get('name', 'unknown')} (PID: {proc.get('pid')})",
                    "severity": "info",
                    "time_source": "psutil.create_time",
                    "time_confidence": "high",
                    "details": {
                        "pid": proc.get("pid"),
                        "ppid": proc.get("ppid"),
                        "path": proc.get("path"),
                        "command_line": proc.get("command_line", "")[:200],
                    },
                })
        return events

    def _extract_from_network(self, network: dict) -> list:
        """从网络信息提取时间线事件."""
        events = []
        # 网络连接通常没有时间戳，但 DNS 缓存可能有 TTL
        dns_cache = network.get("dns_cache", [])
        for entry in dns_cache:
            domain = entry.get("domain", "")
            if domain:
                events.append({
                    "timestamp": datetime.now().isoformat(),
                    "event_type": "network",
                    "source": "network",
                    "description": f"DNS 解析: {domain} -> {entry.get('value', '')}",
                    "severity": "info",
                    "time_source": "collected_at",
                    "time_confidence": "low",
                    "details": entry,
                })
        return events

    def _extract_from_logs(self, logs: dict) -> list:
        """从日志提取时间线事件."""
        events = []
        for log_type in ["system", "security", "application", "syslog"]:
            log_entries = logs.get(log_type, [])
            for entry in log_entries:
                if isinstance(entry, dict):
                    time_str = entry.get("time", "")
                    if not time_str:
                        time_str = datetime.now().isoformat()
                    events.append({
                        "timestamp": time_str,
                        "event_type": "log",
                        "source": f"logs.{log_type}",
                        "description": entry.get("description", entry.get("raw", ""))[:200],
                        "severity": "medium" if log_type == "security" else "info",
                        "time_source": "Windows.EventLog.TimeCreated",
                        "time_confidence": "high",
                        "details": entry,
                    })
        return events

    def _extract_from_files(self, files: dict) -> list:
        """从文件信息提取时间线事件."""
        events = []
        recent_files = files.get("recent_files", [])
        for file_info in recent_files:
            modified = file_info.get("modified")
            if modified:
                events.append({
                    "timestamp": modified,
                    "event_type": "file",
                    "source": "files",
                    "description": f"文件修改: {file_info.get('path', '')}",
                    "severity": "info",
                    "time_source": "os.stat().st_mtime",
                    "time_confidence": "high",
                    "details": file_info,
                })

        suspicious = files.get("suspicious_files", [])
        for file_info in suspicious:
            modified = file_info.get("modified")
            if modified:
                events.append({
                    "timestamp": modified,
                    "event_type": "file",
                    "source": "files",
                    "description": f"可疑文件: {file_info.get('path', '')} - {file_info.get('reason', '')}",
                    "severity": "medium",
                    "time_source": "os.stat().st_mtime",
                    "time_confidence": "medium",
                    "details": file_info,
                })
        return events

    def _extract_from_browser(self, browser: dict) -> list:
        """从浏览器痕迹提取时间线事件."""
        events = []
        for browser_name in ["chrome", "firefox", "edge", "ie"]:
            browser_data = browser.get(browser_name, {})
            history = browser_data.get("history", [])
            for entry in history:
                visit_time = entry.get("visit_time", "")
                if visit_time:
                    events.append({
                        "timestamp": visit_time,
                        "event_type": "network",
                        "source": f"browser.{browser_name}",
                        "description": f"访问网站: {entry.get('title', entry.get('url', ''))[:100]}",
                        "severity": "info",
                        "time_source": "browser.history.visit_time",
                        "time_confidence": "medium",
                        "details": entry,
                    })
        return events

    def _extract_from_security(self, security: dict) -> list:
        """从安全信息提取时间线事件."""
        events = []
        event_summary = security.get("event_ids_summary", {})
        # 安全事件 ID 映射
        important_ids = {
            "4624": "登录成功",
            "4625": "登录失败",
            "4648": "使用显式凭据登录",
            "4672": "管理员权限分配",
            "4688": "进程创建",
            "4720": "用户账户创建",
            "4722": "用户账户启用",
            "4724": "密码重置",
            "4732": "成员添加到本地组",
            "4738": "用户账户更改",
        }
        for event_id, count in event_summary.items():
            if event_id in important_ids:
                events.append({
                    "timestamp": datetime.now().isoformat(),
                    "event_type": "log",
                    "source": "security",
                    "description": f"安全事件 {event_id}: {important_ids[event_id]} (次数: {count})",
                    "severity": "high" if event_id in ["4625", "4720"] else "medium",
                    "time_source": "Windows.EventLog.TimeCreated",
                    "time_confidence": "high",
                    "details": {"event_id": event_id, "count": count},
                })
        return events
