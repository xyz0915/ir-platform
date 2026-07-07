"""12. USB 痕迹采集器."""

import logging
from typing import Any

from collectors.base_collector import BaseCollector
from utils.platform import is_windows, is_linux, run_command

logger = logging.getLogger(__name__)


class UsbCollector(BaseCollector):
    """USB 痕迹采集器.

    采集 USB 设备历史、挂载记录（Windows 注册表 USBSTOR / Linux /var/log）.
    """

    name = "usb"
    platform = ["windows", "linux"]

    def collect(self) -> dict:
        """执行 USB 痕迹采集."""
        if is_windows():
            return self._collect_windows()
        elif is_linux():
            return self._collect_linux()
        return {"devices": [], "mount_history": []}

    def _collect_windows(self) -> dict:
        """Windows USB 痕迹采集."""
        return {
            "devices": self._get_windows_usb_devices(),
            "mount_history": self._get_windows_mount_history(),
        }

    def _get_windows_usb_devices(self) -> list:
        """获取 Windows USB 设备列表（从注册表 USBSTOR）."""
        devices = []
        try:
            import winreg
            usbstor_key = r"SYSTEM\CurrentControlSet\Enum\USBSTOR"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, usbstor_key) as key:
                index = 0
                while True:
                    try:
                        device_type = winreg.EnumKey(key, index)
                        index += 1
                        try:
                            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                                 f"{usbstor_key}\\{device_type}") as type_key:
                                sub_index = 0
                                while True:
                                    try:
                                        device_id = winreg.EnumKey(type_key, sub_index)
                                        sub_index += 1
                                        try:
                                            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                                                 f"{usbstor_key}\\{device_type}\\{device_id}") as dev_key:
                                                try:
                                                    friendly_name, _ = winreg.QueryValueEx(dev_key, "FriendlyName")
                                                except FileNotFoundError:
                                                    friendly_name = device_id
                                                devices.append({
                                                    "device_type": device_type,
                                                    "device_id": device_id,
                                                    "friendly_name": friendly_name,
                                                })
                                        except (FileNotFoundError, PermissionError):
                                            continue
                                    except OSError:
                                        break
                        except (FileNotFoundError, PermissionError):
                            continue
                    except OSError:
                        break
        except (ImportError, FileNotFoundError, PermissionError):
            pass

        # 也检查 USB 设备的挂载驱动器
        output = run_command(
            'powershell -Command "Get-PnpDevice -Class USB | Where-Object {$_.Status -eq \'OK\'} | Select-Object FriendlyName,InstanceId | Format-List" 2>nul',
            timeout=15,
        )
        if output:
            current: dict[str, Any] = {}
            for line in output.split("\n"):
                line = line.strip()
                if ":" in line:
                    key, _, value = line.partition(":")
                    if key.strip() == "FriendlyName":
                        if current:
                            devices.append(current)
                        current = {"friendly_name": value.strip(), "device_type": "USB"}
                    elif key.strip() == "InstanceId":
                        if current:
                            current["instance_id"] = value.strip()
            if current:
                devices.append(current)

        return devices

    def _get_windows_mount_history(self) -> list:
        """获取 Windows USB 挂载历史."""
        history = []
        # 从 MountedDevices 注册表键获取
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\MountedDevices") as key:
                index = 0
                while True:
                    try:
                        name, value, _ = winreg.EnumValue(key, index)
                        index += 1
                        if "\\DosDevices\\" in name:
                            drive_letter = name.split("\\")[-1]
                            history.append({
                                "drive": drive_letter,
                                "device": name,
                            })
                    except OSError:
                        break
        except (ImportError, FileNotFoundError, PermissionError):
            pass
        return history

    def _collect_linux(self) -> dict:
        """Linux USB 痕迹采集."""
        return {
            "devices": self._get_linux_usb_devices(),
            "mount_history": self._get_linux_mount_history(),
        }

    def _get_linux_usb_devices(self) -> list:
        """获取 Linux USB 设备列表."""
        devices = []
        output = run_command("lsusb 2>/dev/null", timeout=10)
        if output:
            for line in output.split("\n"):
                if line.strip():
                    parts = line.split(":", 1)
                    if len(parts) == 2:
                        bus_info = parts[0].strip()
                        device_info = parts[1].strip()
                        devices.append({
                            "bus_info": bus_info,
                            "description": device_info,
                        })
        return devices

    def _get_linux_mount_history(self) -> list:
        """获取 Linux 挂载历史."""
        history = []
        # 从 dmesg 获取 USB 挂载信息
        output = run_command("dmesg 2>/dev/null | grep -i usb", timeout=10)
        if output:
            for line in output.split("\n")[-50:]:
                if "usb" in line.lower() and ("mount" in line.lower() or "connect" in line.lower() or "disconnect" in line.lower()):
                    history.append({"raw": line.strip()})
        return history
