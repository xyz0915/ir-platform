"""1. 系统基础信息采集器."""

import logging
import socket
from typing import Any

from collectors.base_collector import BaseCollector

logger = logging.getLogger(__name__)


class SystemInfoCollector(BaseCollector):
    """系统基础信息采集器.

    采集 hostname、OS 版本、架构、安装日期、运行时间、CPU、内存、磁盘.
    """

    name = "system_info"
    platform = ["windows", "linux"]

    def collect(self) -> dict:
        """执行系统信息采集."""
        try:
            import psutil
        except ImportError:
            psutil = None

        result: dict[str, Any] = {}

        # 基本信息
        result["hostname"] = socket.gethostname()
        result["os"] = self._get_os_name()
        result["os_version"] = self._get_os_version()
        result["architecture"] = self._get_architecture()
        result["install_date"] = self._get_install_date()
        result["uptime_seconds"] = self._get_uptime(psutil)
        result["timezone"] = self._get_timezone()

        # CPU 信息
        result["cpu"] = self._get_cpu_info(psutil)

        # 内存信息
        result["memory"] = self._get_memory_info(psutil)

        # 磁盘信息
        result["disks"] = self._get_disk_info(psutil)

        return result

    def _get_os_name(self) -> str:
        """获取操作系统名称."""
        import platform
        if platform.system() == "Windows":
            return f"Windows {platform.release()}"
        elif platform.system() == "Linux":
            return "Linux"
        return platform.system()

    def _get_os_version(self) -> str:
        """获取操作系统版本."""
        import platform
        return platform.version()

    def _get_architecture(self) -> str:
        """获取系统架构."""
        import platform
        return platform.machine()

    def _get_install_date(self) -> str:
        """获取系统安装日期."""
        from utils.platform import is_windows, run_command
        if is_windows():
            output = run_command(
                'wmic os get InstallDate /value 2>nul'
            )
            for line in output.split("\n"):
                if "=" in line:
                    date_str = line.split("=")[1].strip()
                    if len(date_str) >= 8:
                        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
        else:
            # Linux: 检查 /etc/filesystem 创建时间或 /var/log/installer
            import os
            if os.path.exists("/var/log/installer/syslog"):
                stat = os.stat("/var/log/installer/syslog")
                from datetime import datetime
                return datetime.fromtimestamp(stat.st_ctime).strftime("%Y-%m-%d")
        return ""

    def _get_uptime(self, psutil) -> int:
        """获取系统运行时间（秒）."""
        if psutil:
            import time
            boot_time = psutil.boot_time()
            return int(time.time() - boot_time)
        return 0

    def _get_timezone(self) -> str:
        """获取系统时区."""
        import time
        if hasattr(time, "tzname"):
            tz = time.tzname[0] if time.tzname else ""
            if tz:
                return tz
        # 尝试读取 /etc/timezone (Linux)
        from utils.platform import read_file_safe, is_linux
        if is_linux():
            tz = read_file_safe("/etc/timezone")
            if tz:
                return tz.strip()
        return "UTC"

    def _get_cpu_info(self, psutil) -> dict:
        """获取 CPU 信息."""
        import platform
        info: dict[str, Any] = {}
        if psutil:
            info["model"] = platform.processor() or "Unknown"
            info["cores"] = psutil.cpu_count(logical=False) or 0
            info["logical_cores"] = psutil.cpu_count(logical=True) or 0
        else:
            info["model"] = platform.processor() or "Unknown"
            info["cores"] = 0
            info["logical_cores"] = 0
        return info

    def _get_memory_info(self, psutil) -> dict:
        """获取内存信息."""
        info: dict[str, Any] = {}
        if psutil:
            mem = psutil.virtual_memory()
            info["total_gb"] = round(mem.total / (1024**3), 2)
            info["available_gb"] = round(mem.available / (1024**3), 2)
        else:
            info["total_gb"] = 0
            info["available_gb"] = 0
        return info

    def _get_disk_info(self, psutil) -> list:
        """获取磁盘信息."""
        disks = []
        if psutil:
            for part in psutil.disk_partitions(all=False):
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                    disks.append({
                        "device": part.device,
                        "total_gb": round(usage.total / (1024**3), 2),
                        "free_gb": round(usage.free / (1024**3), 2),
                        "fs_type": part.fstype,
                        "mountpoint": part.mountpoint,
                    })
                except (PermissionError, OSError):
                    continue
        return disks
