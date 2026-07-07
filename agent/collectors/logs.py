"""9. 日志采集器."""

import logging
from typing import Any

from collectors.base_collector import BaseCollector
from utils.platform import is_windows, is_linux, run_command, read_file_lines_safe

logger = logging.getLogger(__name__)


class LogsCollector(BaseCollector):
    """日志采集器.

    采集系统日志、安全日志、应用日志（Windows EventLog / Linux syslog/journalctl）.
    """

    name = "logs"
    platform = ["windows", "linux"]

    def collect(self) -> dict:
        """执行日志采集."""
        if is_windows():
            return self._collect_windows()
        elif is_linux():
            return self._collect_linux()
        return {"system": [], "security": [], "application": [], "syslog": []}

    def _collect_windows(self) -> dict:
        """Windows 日志采集（使用 wevtutil）."""
        return {
            "system": self._get_windows_event_log("System"),
            "security": self._get_windows_event_log("Security"),
            "application": self._get_windows_event_log("Application"),
            "syslog": [],
        }

    def _get_windows_event_log(self, log_name: str, max_events: int = 100) -> list:
        """获取 Windows 事件日志.

        Args:
            log_name: 日志名称（System, Security, Application）.
            max_events: 最大事件数.

        Returns:
            事件列表.
        """
        events = []
        # 使用 wevtutil 查询最近的日志
        output = run_command(
            f'wevtutil qe "{log_name}" /c:{max_events} /f:text /rd:true 2>nul',
            timeout=30,
        )
        if not output:
            return events

        current: dict[str, Any] = {}
        for line in output.split("\n"):
            if line.startswith("Event["):
                if current:
                    events.append(current)
                current = {"log_name": log_name}
            elif ":" in line:
                key, _, value = line.partition(":")
                key = key.strip()
                value = value.strip()
                if key == "EventID":
                    current["event_id"] = value
                elif key == "Type":
                    current["type"] = value
                elif key == "Time":
                    current["time"] = value
                elif key == "Source":
                    current["source"] = value
                elif key == "Computer":
                    current["computer"] = value
                elif key == "Description":
                    current["description"] = value
        if current:
            events.append(current)
        return events

    def _collect_linux(self) -> dict:
        """Linux 日志采集."""
        return {
            "system": self._get_linux_log("/var/log/syslog", fallback_cmd="journalctl --system -n 100 --no-pager 2>/dev/null"),
            "security": self._get_linux_log("/var/log/auth.log", fallback_cmd="journalctl _COMM=sshd -n 100 --no-pager 2>/dev/null"),
            "application": self._get_linux_log("/var/log/messages"),
            "syslog": self._get_linux_log("/var/log/syslog", fallback_cmd="journalctl -n 100 --no-pager 2>/dev/null"),
        }

    def _get_linux_log(self, log_path: str, fallback_cmd: str = "", max_lines: int = 100) -> list:
        """获取 Linux 日志文件内容.

        Args:
            log_path: 日志文件路径.
            fallback_cmd: 文件不存在时的备用命令.
            max_lines: 最大行数.

        Returns:
            日志行列表.
        """
        lines = read_file_lines_safe(log_path)
        if not lines and fallback_cmd:
            output = run_command(fallback_cmd, timeout=15)
            if output:
                lines = output.split("\n")

        result = []
        for line in lines[-max_lines:]:
            if line.strip():
                result.append({"raw": line.strip(), "source": log_path})
        return result
