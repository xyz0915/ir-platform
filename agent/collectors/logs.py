"""9. 日志采集器."""

import logging
from typing import Any

from collectors.base_collector import BaseCollector
from utils.platform import is_windows, is_linux, run_command, read_file_lines_safe, normalize_timestamp

logger = logging.getLogger(__name__)


def _safe_wevtutil_query(
    log_name: str, query: str, max_events: int, timeout: int = 60
) -> str:
    """安全执行 wevtutil 查询，带 timediff 超时 fallback.

    在大型事件日志（尤其是 Security）上，timediff 时间过滤查询可能非常慢。
    此函数先尝试 timediff 查询，超时/失败后自动 fallback 到无时间过滤但限制数量的查询。

    Args:
        log_name: 日志名称（如 System, Security, Application）.
        query: wevtutil 结构化查询字符串（含 timediff 过滤）.
        max_events: 最大事件数.
        timeout: timediff 查询的超时时间（秒），默认 60s.

    Returns:
        命令输出字符串，失败时返回空字符串.
    """
    # 策略 1: 尝试 timediff 时间过滤查询（较长超时）
    cmd = (
        f'wevtutil qe "{log_name}" /q:"{query}" /c:{max_events}'
        f' /f:text /rd:true 2>nul'
    )
    output = run_command(cmd, timeout=timeout)
    if output:
        return output

    # 策略 2: Fallback — 不使用 timediff，只取最近 N 条
    logger.warning(
        "wevtutil timediff query failed/timed out for %s, "
        "falling back to simple query (no time filter)",
        log_name,
    )
    fallback_cmd = (
        f'wevtutil qe "{log_name}" /c:{max_events} /f:text /rd:true 2>nul'
    )
    return run_command(fallback_cmd, timeout=30)


class LogsCollector(BaseCollector):
    """日志采集器.

    采集系统日志、安全日志、应用日志（Windows EventLog / Linux syslog/journalctl）.

    Attributes:
        log_days: 采集最近 N 天的日志数据（默认 7 天）.
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
        """Windows 日志采集（使用 wevtutil + timediff 时间过滤）."""
        return {
            "system": self._get_windows_event_log("System"),
            "security": self._get_windows_event_log("Security"),
            "application": self._get_windows_event_log("Application"),
            "syslog": [],
        }

    def _get_windows_event_log(self, log_name: str, max_events: int = 500) -> list:
        """获取 Windows 事件日志（按时间窗口过滤）.

        Args:
            log_name: 日志名称（System, Security, Application）.
            max_events: 最大事件数.

        Returns:
            事件列表.
        """
        events = []
        # 计算 timediff 阈值（毫秒）：log_days 天
        timediff_ms = self.log_days * 86400 * 1000
        query = f'*[System[TimeCreated[timediff(@SystemTime) <= {timediff_ms}]]]'

        # 使用安全查询（timediff 带 60s 超时 + 无时间过滤 fallback）
        output = _safe_wevtutil_query(log_name, query, max_events, timeout=60)
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
                if key in ("EventID", "Event ID"):
                    current["event_id"] = value
                elif key == "Type":
                    current["type"] = value
                elif key in ("Time", "Date", "Time Created"):
                    current["time"] = normalize_timestamp(value)
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
        """Linux 日志采集（使用 journalctl --since 时间过滤）."""
        since = f"{self.log_days} days ago"
        return {
            "system": self._get_linux_log(
                "/var/log/syslog",
                fallback_cmd=f'journalctl --system --since "{since}" --no-pager 2>/dev/null',
            ),
            "security": self._get_linux_log(
                "/var/log/auth.log",
                fallback_cmd=f'journalctl _COMM=sshd --since "{since}" --no-pager 2>/dev/null',
            ),
            "application": self._get_linux_log(
                "/var/log/messages",
                fallback_cmd=f'journalctl --since "{since}" --no-pager 2>/dev/null',
            ),
            "syslog": self._get_linux_log(
                "/var/log/syslog",
                fallback_cmd=f'journalctl --since "{since}" --no-pager 2>/dev/null',
            ),
        }

    def _get_linux_log(self, log_path: str, fallback_cmd: str = "", max_lines: int = 500) -> list:
        """获取 Linux 日志文件内容.

        Args:
            log_path: 日志文件路径.
            fallback_cmd: 文件不存在时的备用命令（包含 journalctl --since 过滤）.
            max_lines: 最大行数（fallback 到文件时使用）.

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
