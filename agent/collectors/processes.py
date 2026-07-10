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
        """执行进程信息采集（优先 psutil，失败回退 wmic/tasklist）."""
        processes = []

        try:
            import psutil
        except ImportError:
            logger.warning("psutil not available, using fallback")
            return self._collect_fallback()

        # psutil 主采集
        conn_map = self._build_connection_map(psutil)
        try:
            proc_iter = list(psutil.process_iter(["pid", "ppid", "name", "exe", "cmdline",
                                                   "username", "create_time", "num_threads"]))
            if not proc_iter:
                logger.warning("psutil.process_iter returned empty, using fallback")
                return self._collect_fallback()
        except Exception as exc:
            logger.warning("psutil.process_iter failed: %s, using fallback", exc)
            return self._collect_fallback()

        for proc in proc_iter:
            try:
                info = proc.info
                pid = info.get("pid", 0)

                create_time = info.get("create_time")
                start_time = ""
                if create_time:
                    try:
                        start_time = datetime.fromtimestamp(create_time).isoformat()
                    except (ValueError, OSError):
                        start_time = ""

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

    def _collect_fallback(self) -> list:
        """使用 wmic / tasklist 作为 Windows 回退方案."""
        from utils.platform import run_command, is_windows

        if not is_windows():
            return []

        processes = []
        # 方案 A: wmic (CSV 格式，包含命令行)
        output = run_command(
            'wmic process get ProcessId,ParentProcessId,Name,ExecutablePath,CommandLine /format:csv',
            timeout=30,
        )
        if output and "ProcessId" in output:
            lines = output.strip().split("\n")
            if len(lines) > 1:
                header_line = lines[0]
                headers = [h.strip() for h in header_line.split(",")]
                for line in lines[1:]:
                    values = [v.strip() for v in line.split(",")]
                    if len(values) < len(headers):
                        values += [""] * (len(headers) - len(values))
                    row = dict(zip(headers, values))
                    pid_str = row.get("ProcessId", "")
                    if not pid_str or pid_str == "0":
                        continue
                    try:
                        pid = int(pid_str)
                    except ValueError:
                        continue
                    processes.append({
                        "pid": pid,
                        "ppid": int(row.get("ParentProcessId", "0") or "0"),
                        "name": row.get("Name", ""),
                        "path": row.get("ExecutablePath", ""),
                        "command_line": row.get("CommandLine", ""),
                        "user": "",
                        "start_time": "",
                        "threads": 0,
                        "connections": [],
                    })
                return processes

        # 方案 B: tasklist（无命令行，但有 PID/PPID/Name/内存）
        output = run_command('tasklist /fo csv /nh', timeout=15)
        if output:
            import csv, io
            reader = csv.reader(io.StringIO(output.strip()))
            for row in reader:
                if len(row) < 2:
                    continue
                try:
                    name = row[0].strip('"')
                    pid = int(row[1].strip('"'))
                except (ValueError, IndexError):
                    continue
                processes.append({
                    "pid": pid,
                    "ppid": 0,
                    "name": name,
                    "path": "",
                    "command_line": "",
                    "user": "",
                    "start_time": "",
                    "threads": 0,
                    "connections": [],
                })
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
