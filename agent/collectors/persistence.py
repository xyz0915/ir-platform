"""14. 持久化痕迹采集器."""

import logging
from typing import Any

from collectors.base_collector import BaseCollector
from utils.platform import is_windows, is_linux, run_command

logger = logging.getLogger(__name__)


class PersistenceCollector(BaseCollector):
    """持久化痕迹采集器.

    综合采集持久化痕迹：Run 键、计划任务、服务、启动文件夹、WMI、cron、systemd.
    """

    name = "persistence"
    platform = ["windows", "linux"]

    def collect(self) -> dict:
        """执行持久化痕迹采集."""
        if is_windows():
            return self._collect_windows()
        elif is_linux():
            return self._collect_linux()
        return self._empty_result()

    def _empty_result(self) -> dict:
        return {
            "run_keys": [], "scheduled_tasks": [], "services": [],
            "startup_folder": [], "wmi_subscriptions": [],
            "cron_jobs": [], "systemd_units": [], "rc_local": [],
        }

    def _collect_windows(self) -> dict:
        """Windows 持久化痕迹采集."""
        result = self._empty_result()
        result["run_keys"] = self._get_run_keys()
        result["scheduled_tasks"] = self._get_scheduled_tasks()
        result["services"] = self._get_services()
        result["startup_folder"] = self._get_startup_folder()
        result["wmi_subscriptions"] = self._get_wmi_subscriptions()
        return result

    def _get_run_keys(self) -> list:
        """获取注册表 Run 键持久化."""
        items = []
        try:
            import winreg
            run_paths = [
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run", "HKLM"),
                (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run", "HKCU"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce", "HKLM"),
                (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce", "HKCU"),
            ]
            for hive, key_path, hive_name in run_paths:
                try:
                    with winreg.OpenKey(hive, key_path) as key:
                        index = 0
                        while True:
                            try:
                                name, value, _ = winreg.EnumValue(key, index)
                                items.append({
                                    "name": name,
                                    "command": value,
                                    "location": f"{hive_name}\\{key_path}",
                                })
                                index += 1
                            except OSError:
                                break
                except (FileNotFoundError, PermissionError):
                    continue
        except ImportError:
            pass
        return items

    def _get_scheduled_tasks(self) -> list:
        """获取计划任务持久化."""
        items = []
        output = run_command('schtasks /query /fo LIST 2>nul', timeout=30)
        if output:
            current: dict[str, Any] = {}
            for line in output.split("\n"):
                line = line.strip()
                if ":" in line:
                    key, _, value = line.partition(":")
                    key = key.strip()
                    value = value.strip()
                    if key in ("TaskName", "任务名"):
                        if current:
                            items.append(current)
                        current = {"name": value, "command": "", "location": "Task Scheduler"}
                    elif key in ("Task To Run", "要运行的任务"):
                        if current:
                            current["command"] = value
            if current:
                items.append(current)
        return items

    def _get_services(self) -> list:
        """获取服务持久化."""
        items = []
        try:
            import winreg
            services_key = r"SYSTEM\CurrentControlSet\Services"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, services_key) as key:
                index = 0
                while True:
                    try:
                        svc_name = winreg.EnumKey(key, index)
                        index += 1
                        try:
                            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                                 f"{services_key}\\{svc_name}") as subkey:
                                try:
                                    image_path, _ = winreg.QueryValueEx(subkey, "ImagePath")
                                except FileNotFoundError:
                                    image_path = ""
                                try:
                                    start_type, _ = winreg.QueryValueEx(subkey, "Start")
                                except FileNotFoundError:
                                    start_type = 3
                                if image_path:
                                    items.append({
                                        "name": svc_name,
                                        "command": image_path,
                                        "location": f"HKLM\\{services_key}\\{svc_name}",
                                        "start_type": start_type,
                                    })
                        except (FileNotFoundError, PermissionError):
                            continue
                    except OSError:
                        break
        except (ImportError, FileNotFoundError, PermissionError):
            pass
        return items

    def _get_startup_folder(self) -> list:
        """获取启动文件夹持久化."""
        items = []
        import os
        startup_paths = [
            os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows",
                         "Start Menu", "Programs", "Startup"),
            os.path.join(os.environ.get("PROGRAMDATA", ""), "Microsoft", "Windows",
                         "Start Menu", "Programs", "Startup"),
        ]
        for path in startup_paths:
            if path and os.path.exists(path):
                try:
                    for filename in os.listdir(path):
                        items.append({
                            "name": filename,
                            "command": os.path.join(path, filename),
                            "location": path,
                        })
                except (PermissionError, OSError):
                    continue
        return items

    def _get_wmi_subscriptions(self) -> list:
        """获取 WMI 事件订阅持久化."""
        items = []
        output = run_command(
            'powershell -Command "Get-WmiObject -Namespace root\\Subscription -Class __EventConsumer | Select-Object __CLASS, Name | Format-List" 2>nul',
            timeout=15,
        )
        if output:
            current: dict[str, Any] = {}
            for line in output.split("\n"):
                line = line.strip()
                if ":" in line:
                    key, _, value = line.partition(":")
                    if key.strip() == "Name":
                        if current:
                            items.append(current)
                        current = {"name": value.strip(), "type": "wmi_subscription"}
            if current:
                items.append(current)
        return items

    def _collect_linux(self) -> dict:
        """Linux 持久化痕迹采集."""
        result = self._empty_result()
        result["cron_jobs"] = self._get_cron_jobs()
        result["systemd_units"] = self._get_systemd_units()
        result["rc_local"] = self._get_rc_local()
        result["services"] = self._get_linux_services()
        return result

    def _get_cron_jobs(self) -> list:
        """获取 cron 定时任务."""
        items = []
        import os
        cron_locations = ["/etc/crontab", "/etc/cron.d", "/etc/cron.hourly",
                          "/etc/cron.daily", "/etc/cron.weekly", "/etc/cron.monthly"]
        for loc in cron_locations:
            if os.path.isfile(loc):
                output = run_command(f"cat {loc}", timeout=5)
                if output:
                    for line in output.split("\n"):
                        line = line.strip()
                        if line and not line.startswith("#"):
                            items.append({"name": loc, "command": line, "location": loc})
            elif os.path.isdir(loc):
                try:
                    for f in os.listdir(loc):
                        fpath = os.path.join(loc, f)
                        output = run_command(f"cat {fpath}", timeout=5)
                        if output:
                            items.append({"name": f, "command": output, "location": fpath})
                except (PermissionError, OSError):
                    continue
        # 用户 crontab
        output = run_command("crontab -l 2>/dev/null", timeout=5)
        if output:
            for line in output.split("\n"):
                line = line.strip()
                if line and not line.startswith("#"):
                    items.append({"name": "user_crontab", "command": line, "location": "crontab -l"})
        return items

    def _get_systemd_units(self) -> list:
        """获取 systemd 启用单元."""
        items = []
        output = run_command("systemctl list-unit-files --state=enabled --no-pager 2>/dev/null", timeout=15)
        if output:
            for line in output.split("\n"):
                parts = line.split()
                if len(parts) >= 2:
                    items.append({
                        "name": parts[0],
                        "command": "",
                        "location": "systemd",
                        "state": parts[1],
                    })
        return items

    def _get_rc_local(self) -> list:
        """获取 rc.local 持久化."""
        items = []
        import os
        rc_path = "/etc/rc.local"
        if os.path.exists(rc_path):
            output = run_command(f"cat {rc_path}", timeout=5)
            if output:
                for line in output.split("\n"):
                    line = line.strip()
                    if line and not line.startswith("#") and line != "#!/bin/sh":
                        items.append({"name": "rc.local", "command": line, "location": rc_path})
        return items

    def _get_linux_services(self) -> list:
        """获取 Linux 服务列表."""
        items = []
        output = run_command("systemctl list-units --type=service --state=running --no-pager 2>/dev/null", timeout=15)
        if output:
            for line in output.split("\n"):
                parts = line.split()
                if len(parts) >= 4 and parts[0].endswith(".service"):
                    items.append({
                        "name": parts[0],
                        "command": "",
                        "location": "systemd",
                        "status": parts[3],
                    })
        return items
