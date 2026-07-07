"""时间线构建器 — 从采集数据提取时间线事件."""

import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class TimelineBuilder:
    """时间线构建器."""

    @staticmethod
    def build(raw_data: dict) -> list:
        """从采集数据构建时间线.

        Args:
            raw_data: Agent JSON 数据.

        Returns:
            时间线事件列表（已排序）.
        """
        events: list[dict] = []

        # 从进程提取
        events.extend(TimelineBuilder._extract_from_processes(raw_data))

        # 从网络提取
        events.extend(TimelineBuilder._extract_from_network(raw_data))

        # 从日志提取
        events.extend(TimelineBuilder._extract_from_logs(raw_data))

        # 从文件提取
        events.extend(TimelineBuilder._extract_from_files(raw_data))

        # 从浏览器提取
        events.extend(TimelineBuilder._extract_from_browser(raw_data))

        # 从安全事件提取
        events.extend(TimelineBuilder._extract_from_security(raw_data))

        # 从 Agent 原始时间线提取
        agent_timeline = raw_data.get("timeline", [])
        if isinstance(agent_timeline, list):
            for event in agent_timeline:
                if isinstance(event, dict):
                    raw_ts = event.get("timestamp", "")
                    normalized_ts = TimelineBuilder._normalize_timestamp(raw_ts)
                    if normalized_ts:
                        events.append({
                            "timestamp": normalized_ts,
                            "event_type": event.get("event_type", "other"),
                            "source": event.get("source", "agent"),
                            "description": event.get("description", ""),
                            "severity": event.get("severity", "info"),
                            "details": event.get("details", {}),
                        })

        # 排序
        return TimelineBuilder.sort_events(events)

    @staticmethod
    def _normalize_timestamp(ts: str) -> str:
        """将各种时间戳格式统一为 ISO 8601 格式 (YYYY-MM-DDTHH:mm:ss).

        支持的输入格式:
          - ISO with T: 2026-07-03T19:25:46.550278
          - ISO with space: 2026-07-06 08:04:50
          - Slash format: 2026/07/06 08:04:50
          - Slash format with T: 2026/07/06T08:04:50

        Args:
            ts: 原始时间戳字符串.

        Returns:
            标准化后的 ISO 8601 时间戳 (YYYY-MM-DDTHH:mm:ss),
            如果无法解析则返回空字符串.
        """
        if not ts or not isinstance(ts, str):
            return ""

        ts = ts.strip()

        # 尝试多种已知格式解析
        formats = [
            "%Y-%m-%dT%H:%M:%S.%f",    # 2026-07-03T19:25:46.550278
            "%Y-%m-%dT%H:%M:%S",        # 2026-07-03T19:25:46
            "%Y-%m-%d %H:%M:%S.%f",     # 2026-07-06 08:04:50.123456
            "%Y-%m-%d %H:%M:%S",         # 2026-07-06 08:04:50
            "%Y/%m/%dT%H:%M:%S.%f",     # 2026/07/06T08:04:50.123456
            "%Y/%m/%dT%H:%M:%S",         # 2026/07/06T08:04:50
            "%Y/%m/%d %H:%M:%S.%f",     # 2026/07/06 08:04:50.123456
            "%Y/%m/%d %H:%M:%S",         # 2026/07/06 08:04:50
        ]

        for fmt in formats:
            try:
                dt = datetime.strptime(ts, fmt)
                return dt.strftime("%Y-%m-%dT%H:%M:%S")
            except ValueError:
                continue

        # 格式均无法匹配，记录警告并返回空字符串
        logger.warning("无法解析时间戳: %s", ts)
        return ""

    @staticmethod
    def sort_events(events: list) -> list:
        """按时间戳排序事件.

        使用标准化后的时间戳进行排序，确保时间顺序正确.

        Args:
            events: 事件列表.

        Returns:
            排序后的事件列表.
        """
        def _parse_sort_key(event: dict) -> datetime:
            """将时间戳解析为 datetime 用于排序比较."""
            ts = event.get("timestamp", "")
            if not ts:
                return datetime.min
            try:
                return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S")
            except ValueError:
                return datetime.min

        return sorted(events, key=_parse_sort_key)

    @staticmethod
    def _extract_from_processes(raw_data: dict) -> list:
        """从进程信息提取时间线事件.

        过滤掉 start_time 为空的事件（如 System Idle Process）,
        并对时间戳进行标准化.
        """
        events = []
        processes = raw_data.get("processes", [])
        if not isinstance(processes, list):
            return events

        for proc in processes:
            if not isinstance(proc, dict):
                continue
            start_time = proc.get("start_time", "")
            normalized_ts = TimelineBuilder._normalize_timestamp(start_time)
            if normalized_ts:
                events.append({
                    "timestamp": normalized_ts,
                    "event_type": "process",
                    "source": "processes",
                    "description": f"进程启动: {proc.get('name', 'unknown')} (PID: {proc.get('pid')})",
                    "severity": "info",
                    "details": {
                        "pid": proc.get("pid"),
                        "ppid": proc.get("ppid"),
                        "path": proc.get("path", ""),
                        "command_line": proc.get("command_line", "")[:200],
                    },
                })
        return events

    @staticmethod
    def _extract_from_network(raw_data: dict) -> list:
        """从网络信息提取时间线事件.

        DNS 缓存没有真实时间戳,不再使用 datetime.now() 伪造时间.
        仅提取有真实时间戳的网络连接事件.
        """
        events = []
        network = raw_data.get("network", {})
        if not isinstance(network, dict):
            return events

        # DNS 缓存 — 无真实时间戳,跳过不提取
        # DNS 缓存条目没有时间信息,无法放入时间线

        # 提取有真实时间戳的网络连接（如有）
        connections = network.get("connections", [])
        if isinstance(connections, list):
            for entry in connections:
                if isinstance(entry, dict):
                    ts_raw = entry.get("timestamp", entry.get("time", ""))
                    normalized_ts = TimelineBuilder._normalize_timestamp(ts_raw)
                    if normalized_ts:
                        events.append({
                            "timestamp": normalized_ts,
                            "event_type": "network",
                            "source": "network.connections",
                            "description": f"网络连接: {entry.get('local_addr', '')} -> {entry.get('remote_addr', '')}",
                            "severity": "info",
                            "details": entry,
                        })
        return events

    @staticmethod
    def _extract_from_logs(raw_data: dict) -> list:
        """从日志提取时间线事件.

        time 为 None/空时不使用 datetime.now() 作为替代,而是跳过该条目.
        对所有时间戳进行标准化.
        """
        events = []
        logs = raw_data.get("logs", {})
        if not isinstance(logs, dict):
            return events

        for log_type in ["system", "security", "application", "syslog"]:
            log_entries = logs.get(log_type, [])
            if not isinstance(log_entries, list):
                continue
            for entry in log_entries:
                if isinstance(entry, dict):
                    time_str = entry.get("time", "")
                    # 不再使用 datetime.now() 替代空时间戳
                    # 空时间戳的日志条目无法放入时间线,跳过
                    normalized_ts = TimelineBuilder._normalize_timestamp(time_str)
                    if normalized_ts:
                        events.append({
                            "timestamp": normalized_ts,
                            "event_type": "log",
                            "source": f"logs.{log_type}",
                            "description": entry.get("description", entry.get("raw", ""))[:200],
                            "severity": "medium" if log_type == "security" else "info",
                            "details": entry,
                        })
        return events

    @staticmethod
    def _extract_from_files(raw_data: dict) -> list:
        """从文件信息提取时间线事件.

        对所有时间戳进行标准化.
        """
        events = []
        files = raw_data.get("files", {})
        if not isinstance(files, dict):
            return events

        recent_files = files.get("recent_files", [])
        if isinstance(recent_files, list):
            for file_info in recent_files:
                if isinstance(file_info, dict):
                    modified = file_info.get("modified", "")
                    normalized_ts = TimelineBuilder._normalize_timestamp(modified)
                    if normalized_ts:
                        events.append({
                            "timestamp": normalized_ts,
                            "event_type": "file",
                            "source": "files.recent",
                            "description": f"文件修改: {file_info.get('path', '')}",
                            "severity": "info",
                            "details": file_info,
                        })

        suspicious = files.get("suspicious_files", [])
        if isinstance(suspicious, list):
            for file_info in suspicious:
                if isinstance(file_info, dict):
                    modified = file_info.get("modified", "")
                    normalized_ts = TimelineBuilder._normalize_timestamp(modified)
                    if normalized_ts:
                        events.append({
                            "timestamp": normalized_ts,
                            "event_type": "file",
                            "source": "files.suspicious",
                            "description": f"可疑文件: {file_info.get('path', '')} — {file_info.get('reason', '')}",
                            "severity": "medium",
                            "details": file_info,
                        })
        return events

    @staticmethod
    def _extract_from_browser(raw_data: dict) -> list:
        """从浏览器痕迹提取时间线事件.

        对所有时间戳进行标准化,将空格分隔的格式转换为 ISO T 格式.
        """
        events = []
        browser = raw_data.get("browser", {})
        if not isinstance(browser, dict):
            return events

        for browser_name in ["chrome", "firefox", "edge", "ie"]:
            browser_data = browser.get(browser_name, {})
            if not isinstance(browser_data, dict):
                continue
            history = browser_data.get("history", [])
            if isinstance(history, list):
                for entry in history:
                    if isinstance(entry, dict):
                        visit_time = entry.get("visit_time", "")
                        normalized_ts = TimelineBuilder._normalize_timestamp(visit_time)
                        if normalized_ts:
                            events.append({
                                "timestamp": normalized_ts,
                                "event_type": "network",
                                "source": f"browser.{browser_name}",
                                "description": f"访问网站: {entry.get('title', entry.get('url', ''))[:100]}",
                                "severity": "info",
                                "details": entry,
                            })
        return events

    @staticmethod
    def _extract_from_security(raw_data: dict) -> list:
        """从安全信息提取时间线事件.

        安全事件摘要(event_ids_summary)没有具体时间戳,
        不再使用 datetime.now() 伪造时间.
        改为从安全日志条目中提取有真实时间的具体事件.
        """
        events = []
        security = raw_data.get("security", {})
        if not isinstance(security, dict):
            return events

        # 从安全日志中提取有真实时间戳的条目（而非摘要统计）
        # 安全日志条目位于 logs.security 中,已在 _extract_from_logs 中处理

        # event_ids_summary 是统计汇总,没有具体时间戳,不提取到时间线

        # 如果 security 中有具体的 event_records（带时间戳的条目）,提取它们
        event_records = security.get("event_records", [])
        if isinstance(event_records, list):
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
            for record in event_records:
                if isinstance(record, dict):
                    ts_raw = record.get("time", record.get("timestamp", ""))
                    normalized_ts = TimelineBuilder._normalize_timestamp(ts_raw)
                    event_id = str(record.get("event_id", ""))
                    if normalized_ts and event_id in important_ids:
                        events.append({
                            "timestamp": normalized_ts,
                            "event_type": "log",
                            "source": "security.events",
                            "description": f"安全事件 {event_id}: {important_ids[event_id]}",
                            "severity": "high" if event_id in ["4625", "4720"] else "medium",
                            "details": {
                                "event_id": event_id,
                                "description": record.get("description", ""),
                            },
                        })
        return events
