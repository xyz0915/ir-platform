"""13. 远控痕迹采集器."""

import logging
import os
from typing import Any

from collectors.base_collector import BaseCollector
from utils.platform import is_windows, is_linux, run_command, read_file_safe

logger = logging.getLogger(__name__)

# 远控软件检测配置
REMOTE_TOOLS = {
    "teamviewer": {
        "process_names": ["teamviewer", "TeamViewer.exe"],
        "win_paths": [r"C:\Program Files\TeamViewer", r"C:\Program Files (x86)\TeamViewer"],
        "linux_paths": ["/opt/teamviewer"],
        "reg_keys": [r"SOFTWARE\TeamViewer"],
    },
    "anydesk": {
        "process_names": ["anydesk", "AnyDesk.exe"],
        "win_paths": [r"C:\Program Files\AnyDesk", os.path.expanduser(r"~\AppData\Roaming\AnyDesk")],
        "linux_paths": ["/usr/bin/anydesk", os.path.expanduser("~/.anydesk")],
        "reg_keys": [r"SOFTWARE\AnyDesk"],
    },
    "vnc": {
        "process_names": ["vncserver", "vncviewer", "winvnc", "tvnserver", "vncsvc"],
        "win_paths": [r"C:\Program Files\RealVNC", r"C:\Program Files\uvnc"],
        "linux_paths": ["/usr/bin/vncserver", "/usr/bin/vncviewer"],
        "reg_keys": [r"SOFTWARE\RealVNC", r"SOFTWARE\ORL\WinVNC3"],
    },
    "rustdesk": {
        "process_names": ["rustdesk", "RustDesk.exe"],
        "win_paths": [r"C:\Program Files\RustDesk"],
        "linux_paths": ["/usr/bin/rustdesk"],
        "reg_keys": [r"SOFTWARE\RustDesk"],
    },
    "sunlogin": {
        "process_names": ["sunloginclient", "SunloginClient.exe"],
        "win_paths": [r"C:\Program Files\Oray\SunLogin"],
        "linux_paths": ["/usr/local/sunlogin"],
        "reg_keys": [r"SOFTWARE\Oray\SunLogin"],
    },
}


class RemoteControlCollector(BaseCollector):
    """远控痕迹采集器.

    采集 TeamViewer/AnyDesk/VNC/RustDesk/向日葵 安装与连接痕迹.
    """

    name = "remote_control"
    platform = ["windows", "linux"]

    def collect(self) -> dict:
        """执行远控痕迹采集."""
        result = {}
        for tool_name in REMOTE_TOOLS:
            result[tool_name] = self._check_tool(tool_name, REMOTE_TOOLS[tool_name])
        return result

    def _check_tool(self, tool_name: str, config: dict) -> dict:
        """检查单个远控软件的安装和运行状态.

        Args:
            tool_name: 远控软件名称.
            config: 检测配置.

        Returns:
            检测结果字典.
        """
        result: dict[str, Any] = {
            "installed": False,
            "running": False,
            "install_path": "",
            "processes": [],
            "connections": [],
            "config_files": [],
        }

        # 检查进程
        try:
            import psutil
            for proc in psutil.process_iter(["name", "pid", "exe"]):
                try:
                    proc_name = proc.info.get("name", "") or ""
                    if proc_name.lower() in [n.lower() for n in config["process_names"]]:
                        result["running"] = True
                        result["processes"].append({
                            "pid": proc.info.get("pid"),
                            "name": proc_name,
                            "path": proc.info.get("exe", "") or "",
                        })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except ImportError:
            pass

        # 检查安装路径
        if is_windows():
            paths = config.get("win_paths", [])
        else:
            paths = config.get("linux_paths", [])

        for path in paths:
            if path and os.path.exists(path):
                result["installed"] = True
                result["install_path"] = path
                break

        # 检查注册表（Windows）
        if is_windows():
            try:
                import winreg
                for reg_key in config.get("reg_keys", []):
                    try:
                        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, reg_key):
                            result["installed"] = True
                            if not result["install_path"]:
                                result["install_path"] = f"HKLM\\{reg_key}"
                    except (FileNotFoundError, PermissionError):
                        continue
            except ImportError:
                pass

        # 检查配置文件
        if is_windows():
            config_dirs = [
                os.path.expanduser(r"~\AppData\Roaming"),
                os.path.expanduser(r"~\AppData\Local"),
            ]
        else:
            config_dirs = [os.path.expanduser("~/.config"), os.path.expanduser("~")]

        for config_dir in config_dirs:
            if os.path.exists(config_dir):
                try:
                    for item in os.listdir(config_dir):
                        if tool_name.lower() in item.lower():
                            result["config_files"].append(os.path.join(config_dir, item))
                except (PermissionError, OSError):
                    continue

        # 检查网络连接
        if result["running"]:
            try:
                import psutil
                for proc in result["processes"]:
                    pid = proc.get("pid")
                    if pid:
                        try:
                            p = psutil.Process(pid)
                            for conn in p.connections():
                                if conn.status == "ESTABLISHED":
                                    result["connections"].append({
                                        "local": f"{conn.laddr.ip}:{conn.laddr.port}" if conn.laddr else "",
                                        "remote": f"{conn.raddr.ip}:{conn.raddr.port}" if conn.raddr else "",
                                        "state": conn.status,
                                    })
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            continue
            except ImportError:
                pass

        return result
