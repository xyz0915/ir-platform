"""8. 注册表采集器（Windows 专用）."""

import logging
from typing import Any

from collectors.base_collector import BaseCollector
from utils.platform import is_windows, run_command, get_timestamp

logger = logging.getLogger(__name__)

# winreg 类型常量到字符串名称的映射
_REG_TYPE_MAP: dict[int, str] = {
    0: "REG_NONE",
    1: "REG_SZ",
    2: "REG_EXPAND_SZ",
    3: "REG_BINARY",
    4: "REG_DWORD",
    5: "REG_DWORD_BIG_ENDIAN",
    6: "REG_LINK",
    7: "REG_MULTI_SZ",
    8: "REG_RESOURCE_LIST",
    9: "REG_FULL_RESOURCE_DESCRIPTOR",
    10: "REG_RESOURCE_REQUIREMENTS_LIST",
    11: "REG_QWORD",
}


def _reg_type_name(type_value: int) -> str:
    """将 winreg 类型常量映射为可读字符串."""
    return _REG_TYPE_MAP.get(type_value, f"REG_UNKNOWN_{type_value}")


class RegistryCollector(BaseCollector):
    """注册表采集器（Windows 专用）.

    采集 Run 键、服务、计划任务、Shell 扩展、AMT 配置，
    以及平台所需的扁平化 registry_keys 列表.
    """

    name = "registry"
    platform = ["windows"]

    def collect(self) -> dict:
        """执行注册表采集."""
        run_keys = self._get_run_keys()
        services = self._get_registry_services()
        shell_extensions = self._get_shell_extensions()

        return {
            "run_keys": run_keys,
            "services": services,
            "scheduled_tasks": self._get_scheduled_tasks_registry(),
            "shell_extensions": shell_extensions,
            "registry_keys": self._build_registry_keys(run_keys, services, shell_extensions),
        }

    def _build_registry_keys(self, run_keys: list, services: list,
                             shell_extensions: list) -> list:
        """将 run_keys / services / shell_extensions 扁平化为 registry_keys 列表.

        每项包含:
          key_path, value_name, value_type, value_data,
          last_write_time, collected_at.
        """
        items: list[dict[str, Any]] = []
        now = get_timestamp()

        # 从 run_keys 平铺
        for rk in run_keys:
            items.append({
                "key_path": rk.get("key", ""),
                "value_name": rk.get("name", ""),
                "value_type": rk.get("value_type", "REG_SZ"),
                "value_data": str(rk.get("value", "")),
                "last_write_time": "",
                "collected_at": now,
            })

        # 从 services 平铺
        for svc in services:
            name = svc.get("name", "")
            if name:
                items.append({
                    "key_path": f"HKLM\\SYSTEM\\CurrentControlSet\\Services\\{name}",
                    "value_name": "ImagePath",
                    "value_type": "REG_EXPAND_SZ",
                    "value_data": svc.get("image_path", ""),
                    "last_write_time": "",
                    "collected_at": now,
                })

        # 从 shell_extensions 平铺
        for se in shell_extensions:
            items.append({
                "key_path": se.get("key", ""),
                "value_name": se.get("name", ""),
                "value_type": se.get("value_type", "REG_SZ"),
                "value_data": str(se.get("value", "")),
                "last_write_time": "",
                "collected_at": now,
            })

        return items

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
                            name, value, value_type = winreg.EnumValue(key, index)
                            items.append({
                                "key": f"{key_path}\\{name}",
                                "name": name,
                                "value": value,
                                "hive": "HKLM" if hive == winreg.HKEY_LOCAL_MACHINE else "HKCU",
                                "value_type": _reg_type_name(value_type),
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
                                name, value, value_type = winreg.EnumValue(key, index)
                                items.append({
                                    "key": ext_path,
                                    "name": name,
                                    "value": value,
                                    "value_type": _reg_type_name(value_type),
                                })
                                index += 1
                            except OSError:
                                break
                except (FileNotFoundError, PermissionError):
                    continue
        except ImportError:
            pass
        return items
