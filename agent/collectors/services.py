"""4. 服务信息采集器."""

import logging
from typing import Any

from collectors.base_collector import BaseCollector
from utils.platform import is_windows, is_linux, run_command, get_timestamp

logger = logging.getLogger(__name__)


class ServicesCollector(BaseCollector):
    """服务信息采集器.

    采集服务名、显示名、状态、启动类型、二进制路径、运行账户.
    """

    name = "services"
    platform = ["windows", "linux"]

    def collect(self) -> list:
        """执行服务信息采集."""
        if is_windows():
            return self._collect_windows()
        elif is_linux():
            return self._collect_linux()
        return []

    def _collect_windows(self) -> list:
        """Windows 服务采集（使用 sc query）."""
        services = []
        output = run_command("sc query state= all", timeout=30)
        if not output:
            return services

        current: dict[str, Any] = {}
        for line in output.split("\n"):
            line = line.strip()
            if line.startswith("SERVICE_NAME") or line.startswith("服务名称"):
                if current:
                    services.append(current)
                current = {"name": line.split(":", 1)[-1].strip() if ":" in line else "",
                            "collected_at": get_timestamp(),
                            "dedup_key": f"service:{line.split(':', 1)[-1].strip() if ':' in line else ''}"}
            elif line.startswith("DISPLAY_NAME") or line.startswith("显示名称"):
                current["display_name"] = line.split(":", 1)[-1].strip() if ":" in line else ""
            elif line.startswith("STATE") or line.startswith("状态"):
                state_val = line.split(":", 1)[-1].strip() if ":" in line else line
                current["status"] = "running" if "RUNNING" in state_val.upper() else "stopped"
            elif "BINARY_PATH_NAME" in line.upper() or "二进制路径" in line:
                current["binary_path"] = line.split(":", 1)[-1].strip() if ":" in line else ""

        if current:
            services.append(current)

        # 获取启动类型
        for svc in services:
            svc_name = svc.get("name", "")
            if svc_name:
                qc_output = run_command(f'sc qc "{svc_name}"', timeout=5)
                if qc_output:
                    for qline in qc_output.split("\n"):
                        if "START_TYPE" in qline.upper() or "启动类型" in qline:
                            start_val = qline.split(":", 1)[-1].strip() if ":" in qline else ""
                            if "AUTO" in start_val.upper():
                                svc["start_type"] = "auto"
                            elif "DEMAND" in start_val.upper() or "MANUAL" in start_val.upper():
                                svc["start_type"] = "manual"
                            elif "DISABLED" in start_val.upper():
                                svc["start_type"] = "disabled"
                            else:
                                svc["start_type"] = start_val
                        if "SERVICE_START_NAME" in qline.upper() or "账户" in qline:
                            svc["account"] = qline.split(":", 1)[-1].strip() if ":" in qline else ""
                if "start_type" not in svc:
                    svc["start_type"] = "unknown"
                if "account" not in svc:
                    svc["account"] = ""

        return services

    def _collect_linux(self) -> list:
        """Linux 服务采集（使用 systemctl）."""
        services = []
        output = run_command("systemctl list-units --type=service --all --no-pager", timeout=30)
        if output:
            for line in output.split("\n"):
                parts = line.split()
                if len(parts) >= 4 and parts[0].endswith(".service"):
                    svc_name = parts[0].replace(".service", "")
                    load_state = parts[1] if len(parts) > 1 else ""
                    active_state = parts[2] if len(parts) > 2 else ""
                    status = "running" if active_state == "active" else "stopped"
                    services.append({
                        "name": svc_name,
                        "display_name": svc_name,
                        "status": status,
                        "start_type": "auto" if "enabled" in load_state else "manual",
                        "binary_path": "",
                        "account": "",
                        "collected_at": get_timestamp(),
                    })
        return services
