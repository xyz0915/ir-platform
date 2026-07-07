"""3. 进程信息采集器."""

import logging
from datetime import datetime
from typing import Any

from collectors.base_collector import BaseCollector

logger = logging.getLogger(__name__)


class ProcessesCollector(BaseCollector):
    """进程信息采集器.

    采集 PID、PPID、进程名、路径、命令行、用户、启动时间、线程数、网络连接.
    """

    name = "processes"
    platform = ["windows", "linux"]

    def collect(self) -> list:
        """执行进程信息采集."""
        try:
            import psutil
        except ImportError:
            logger.error("psutil not available")
            return []

        processes = []
        # 构建网络连接到 PID 的映射
        conn_map = self._build_connection_map(psutil)

        for proc in psutil.process_iter(["pid", "ppid", "name", "exe", "cmdline",
                                         "username", "create_time", "num_threads"]):
            try:
                info = proc.info
                pid = info.get("pid", 0)

                # 格式化启动时间
                create_time = info.get("create_time")
                start_time = ""
                if create_time:
                    try:
                        start_time = datetime.fromtimestamp(create_time).isoformat()
                    except (ValueError, OSError):
                        start_time = ""

                # 获取命令行
                cmdline = info.get("cmdline")
                command_line = " ".join(cmdline) if cmdline else ""

                process_data = {
                    "pid": pid,
                    "ppid": info.get("ppid", 0),
                    "name": info.get("name", ""),
                    "path": info.get("exe", "") or "",
                    "command_line": command_line,
                    "user": info.get("username", "") or "",
                    "start_time": start_time,
                    "threads": info.get("num_threads", 0) or 0,
                    "connections": conn_map.get(pid, []),
                }
                processes.append(process_data)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        return processes

    def _build_connection_map(self, psutil) -> dict:
        """构建 PID → 网络连接列表的映射.

        Args:
            psutil: psutil 模块.

        Returns:
            {pid: [{"local_address": ..., "remote_address": ..., ...}]}
        """
        conn_map: dict[int, list] = {}
        try:
            connections = psutil.net_connections(kind="inet")
            for conn in connections:
                pid = conn.pid
                if pid is None:
                    continue
                if pid not in conn_map:
                    conn_map[pid] = []
                conn_map[pid].append({
                    "protocol": "TCP" if conn.type.name == "SOCK_STREAM" else "UDP",
                    "local_address": conn.laddr.ip if conn.laddr else "",
                    "local_port": conn.laddr.port if conn.laddr else 0,
                    "remote_address": conn.raddr.ip if conn.raddr else "",
                    "remote_port": conn.raddr.port if conn.raddr else 0,
                    "state": conn.status if conn.status else "",
                })
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            pass
        return conn_map
