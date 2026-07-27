"""5. 启动项采集器."""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from collectors.base_collector import BaseCollector
from utils.platform import is_windows, is_linux, run_command, get_timestamp

logger = logging.getLogger(__name__)


class StartupItemsCollector(BaseCollector):
    """启动项采集器.

    采集注册表 Run 键、启动文件夹、计划任务（Windows）；
    systemd/cron/rc.local（Linux）.
    """

    name = "startup_items"
    platform = ["windows", "linux"]

    def collect(self) -> list:
        """执行启动项采集."""
        if is_windows():
            return self._collect_windows()
        elif is_linux():
            return self._collect_linux()
        return []

    def _collect_windows(self) -> list:
        """Windows 启动项采集."""
        items = []

        # 注册表 Run 键
        items.extend(self._get_registry_run_keys())

        # 启动文件夹
        items.extend(self._get_startup_folder())

        # 计划任务
        items.extend(self._get_scheduled_tasks())

        return items

    def _get_registry_run_keys(self) -> list:
        """获取注册表 Run 键下的启动项."""
        items = []
        try:
            import winreg
        except ImportError:
            return items

        run_keys = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run", "HKLM", "all"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Run", "HKLM-WOW64", "all"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run", "HKCU", "current"),
        ]

        for hive, key_path, location, user in run_keys:
            try:
                with winreg.OpenKey(hive, key_path) as key:
                    # L66-73: 获取注册表键的最后写入时间
                    # winreg.QueryInfoKey[2] 在 Python 3.13 上返回 FILETIME int
                    # (100-ns 间隔自 1601-01-01 UTC)，早期版本返回 datetime
                    try:
                        info = winreg.QueryInfoKey(key)
                        lwt_raw = info[2]
                        if isinstance(lwt_raw, int):
                            # FILETIME → datetime
                            filetime_epoch = datetime(1601, 1, 1, tzinfo=timezone.utc)
                            seconds = lwt_raw / 10_000_000.0
                            last_write_str = (filetime_epoch + timedelta(seconds=seconds)).isoformat()
                        else:
                            try:
                                last_write_str = lwt_raw.isoformat()
                            except Exception:
                                last_write_str = ""
                    except Exception:
                        last_write_str = ""
                    index = 0
                    while True:
                        try:
                            name, value, _ = winreg.EnumValue(key, index)
                            items.append({
                                "name": name,
                                "command": value,
                                "location": f"{location}\\{key_path}",
                                "user": user,
                                "type": "registry",
                                "last_write_time": last_write_str,
                                "collected_at": get_timestamp(),
                                "dedup_key": f"run:{location}:{key_path}:{name}",
                            })
                            index += 1
                        except OSError:
                            break
            except (FileNotFoundError, PermissionError):
                continue
        return items

    def _get_startup_folder(self) -> list:
        """获取启动文件夹中的项目."""
        items = []
        startup_paths = []

        # 当前用户启动文件夹
        user_profile = os.environ.get("USERPROFILE", "")
        if user_profile:
            startup_paths.append(os.path.join(user_profile, "AppData", "Roaming",
                                               "Microsoft", "Windows", "Start Menu",
                                               "Programs", "Startup"))

        # 所有用户启动文件夹
        all_users = os.environ.get("PROGRAMDATA", "")
        if all_users:
            startup_paths.append(os.path.join(all_users, "Microsoft", "Windows",
                                               "Start Menu", "Programs", "Startup"))

        for path in startup_paths:
            if not os.path.exists(path):
                continue
            user = "current" if "Roaming" in path else "all"
            try:
                for filename in os.listdir(path):
                    filepath = os.path.join(path, filename)
                    items.append({
                        "name": filename,
                        "command": filepath,
                        "location": path,
                        "user": user,
                        "type": "startup_folder",
                        "last_write_time": datetime.fromtimestamp(
                            os.path.getmtime(filepath), tz=timezone.utc
                        ).isoformat(),
                        "collected_at": get_timestamp(),
                    })
            except (PermissionError, OSError):
                continue
        return items

    def _get_scheduled_tasks(self) -> list:
        """获取计划任务."""
        items = []
        output = run_command('schtasks /query /fo LIST /v 2>nul', timeout=30)
        if not output:
            return items

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
                    # 从任务名构造系统 Tasks 目录下的文件路径
                    normalized_name = value.lstrip("\\")
                    task_file_path = os.path.join(
                        os.environ.get("SystemRoot", "C:\\Windows"),
                        "System32", "Tasks", normalized_name,
                    )
                    task_lwt = ""
                    try:
                        mtime = os.path.getmtime(task_file_path)
                        task_lwt = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
                    except OSError:
                        pass
                    current = {
                        "name": value,
                        "command": "",
                        "location": "Task Scheduler",
                        "user": "",
                        "type": "scheduled_task",
                        "last_write_time": task_lwt,
                        "collected_at": get_timestamp(),
                        "dedup_key": f"task:{value}",
                    }
                elif key in ("Task To Run", "要运行的任务"):
                    if current:
                        current["command"] = value
                elif key in ("Run As User", "运行身份"):
                    if current:
                        current["user"] = value
        if current:
            items.append(current)
        return items

    def _collect_linux(self) -> list:
        """Linux 启动项采集."""
        items = []

        # systemd 服务
        output = run_command("systemctl list-unit-files --type=service --state=enabled --no-pager", timeout=15)
        if output:
            for line in output.split("\n"):
                parts = line.split()
                if len(parts) >= 2 and parts[0].endswith(".service"):
                    items.append({
                        "name": parts[0],
                        "command": "",
                        "location": "/etc/systemd/system",
                        "user": "root",
                        "type": "systemd",
                    })

        # cron 任务
        items.extend(self._get_cron_jobs())

        # rc.local
        rc_local = "/etc/rc.local"
        if os.path.exists(rc_local):
            content = run_command(f"cat {rc_local}", timeout=5)
            if content:
                items.append({
                    "name": "rc.local",
                    "command": rc_local,
                    "location": rc_local,
                    "user": "root",
                    "type": "rc_local",
                })

        return items

    def _get_cron_jobs(self) -> list:
        """获取 cron 定时任务."""
        items = []
        cron_files = ["/etc/crontab", "/etc/cron.d"]
        for cron_file in cron_files:
            if os.path.isfile(cron_file):
                output = run_command(f"cat {cron_file}", timeout=5)
                if output:
                    for line in output.split("\n"):
                        line = line.strip()
                        if line and not line.startswith("#"):
                            items.append({
                                "name": "cron_job",
                                "command": line,
                                "location": cron_file,
                                "user": "root",
                                "type": "cron",
                            })
            elif os.path.isdir(cron_file):
                try:
                    for f in os.listdir(cron_file):
                        fpath = os.path.join(cron_file, f)
                        if os.path.isfile(fpath):
                            output = run_command(f"cat {fpath}", timeout=5)
                            if output:
                                for line in output.split("\n"):
                                    line = line.strip()
                                    if line and not line.startswith("#"):
                                        items.append({
                                            "name": f"cron_{f}",
                                            "command": line,
                                            "location": fpath,
                                            "user": "root",
                                            "type": "cron",
                                        })
                except (PermissionError, OSError):
                    continue
        return items
