"""8. 注册表采集器（Windows 专用）."""

import logging
from typing import Any

from collectors.base_collector import BaseCollector
from utils.platform import is_windows, run_command

logger = logging.getLogger(__name__)


class RegistryCollector(BaseCollector):
    """注册表采集器（Windows 专用）.

    采集 Run 键、服务、计划任务、Shell 扩展、AMT 配置.
    """

    name = "registry"
    platform = ["windows"]

    def collect(self) -> dict:
        """执行注册表采集."""
        return {
            "run_keys": self._get_run_keys(),
            "services": self._get_registry_services(),
            "scheduled_tasks": self._get_scheduled_tasks_registry(),
            "shell_extensions": self._get_shell_extensions(),
        }

    def _get_run_keys(self) -> list:
        """获取注册表 Run 键."""
        items = []
        try:
            import winreg
        except ImportError:
            return items

        run_paths = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Run"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce"),
        ]

        for hive, key_path in run_paths:
            try:
                with winreg.OpenKey(hive, key_path) as key:
                    index = 0
                    while True:
                        try:
                            name, value, _ = winreg.EnumValue(key, index)
                            items.append({
                                "key": f"{key_path}\\{name}",
                                "name": name,
                                "value": value,
                                "hive": "HKLM" if hive == winreg.HKEY_LOCAL_MACHINE else "HKCU",
                            })
                            index += 1
                        except OSError:
                            break
            except (FileNotFoundError, PermissionError):
                continue
        return items

    def _get_registry_services(self) -> list:
        """获取注册表中的服务配置."""
        items = []
        try:
            import winreg
            services_key = r"SYSTEM\CurrentControlSet\Services"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, services_key) as key:
                index = 0
                while True:
                    try:
                        subkey_name = winreg.EnumKey(key, index)
                        index += 1
                        try:
                            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                                 f"{services_key}\\{subkey_name}") as subkey:
                                try:
                                    image_path, _ = winreg.QueryValueEx(subkey, "ImagePath")
                                except FileNotFoundError:
                                    image_path = ""
                                try:
                                    start_type, _ = winreg.QueryValueEx(subkey, "Start")
                                    start_map = {0: "boot", 1: "system", 2: "auto", 3: "manual", 4: "disabled"}
                                    start_type = start_map.get(start_type, str(start_type))
                                except FileNotFoundError:
                                    start_type = "unknown"
                                items.append({
                                    "name": subkey_name,
                                    "image_path": image_path,
                                    "start_type": start_type,
                                })
                        except (FileNotFoundError, PermissionError):
                            continue
                    except OSError:
                        break
        except (ImportError, FileNotFoundError, PermissionError):
            pass
        return items

    def _get_scheduled_tasks_registry(self) -> list:
        """获取注册表中的计划任务信息."""
        items = []
        try:
            import winreg
            task_key = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Schedule\TaskCache\Tasks"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, task_key) as key:
                index = 0
                while True:
                    try:
                        subkey_name = winreg.EnumKey(key, index)
                        index += 1
                        try:
                            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                                 f"{task_key}\\{subkey_name}") as subkey:
                                try:
                                    path, _ = winreg.QueryValueEx(subkey, "Path")
                                except FileNotFoundError:
                                    path = ""
                                items.append({
                                    "guid": subkey_name,
                                    "path": path,
                                })
                        except (FileNotFoundError, PermissionError):
                            continue
                    except OSError:
                        break
        except (ImportError, FileNotFoundError, PermissionError):
            pass
        return items

    def _get_shell_extensions(self) -> list:
        """获取 Shell 扩展注册项."""
        items = []
        try:
            import winreg
            shell_ext_paths = [
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Shell Extensions\Approved",
                r"SOFTWARE\Classes\*\ShellEx",
            ]
            for ext_path in shell_ext_paths:
                try:
                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, ext_path) as key:
                        index = 0
                        while True:
                            try:
                                name, value, _ = winreg.EnumValue(key, index)
                                items.append({
                                    "key": ext_path,
                                    "name": name,
                                    "value": value,
                                })
                                index += 1
                            except OSError:
                                break
                except (FileNotFoundError, PermissionError):
                    continue
        except ImportError:
            pass
        return items
