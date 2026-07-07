"""6. 网络信息采集器."""

import logging
import socket
from typing import Any

from collectors.base_collector import BaseCollector
from utils.platform import is_windows, is_linux, run_command, read_file_safe

logger = logging.getLogger(__name__)


class NetworkCollector(BaseCollector):
    """网络信息采集器.

    采集网络连接、网卡接口、DNS 缓存、hosts 文件、路由表.
    """

    name = "network"
    platform = ["windows", "linux"]

    def collect(self) -> dict:
        """执行网络信息采集."""
        result: dict[str, Any] = {
            "connections": self._get_connections(),
            "interfaces": self._get_interfaces(),
            "dns_cache": self._get_dns_cache(),
            "hosts_file": self._get_hosts_file(),
            "routing_table": self._get_routing_table(),
        }
        return result

    def _get_connections(self) -> list:
        """获取网络连接列表."""
        connections = []
        try:
            import psutil
            for conn in psutil.net_connections(kind="inet"):
                try:
                    process_name = ""
                    pid = conn.pid
                    if pid:
                        try:
                            process_name = psutil.Process(pid).name()
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass
                    connections.append({
                        "protocol": "TCP" if conn.type.name == "SOCK_STREAM" else "UDP",
                        "local_address": conn.laddr.ip if conn.laddr else "",
                        "local_port": conn.laddr.port if conn.laddr else 0,
                        "remote_address": conn.raddr.ip if conn.raddr else "",
                        "remote_port": conn.raddr.port if conn.raddr else 0,
                        "state": conn.status if conn.status else "",
                        "pid": pid or 0,
                        "process_name": process_name,
                    })
                except Exception:
                    continue
        except ImportError:
            pass
        return connections

    def _get_interfaces(self) -> list:
        """获取网卡接口信息."""
        interfaces = []
        try:
            import psutil
            import socket as sock_module

            stats = psutil.net_if_stats()
            addrs = psutil.net_if_addrs()

            for name, stat in stats.items():
                iface: dict[str, Any] = {
                    "name": name,
                    "ip": "",
                    "mac": "",
                    "netmask": "",
                    "gateway": "",
                    "isup": stat.isup,
                    "speed": stat.speed,
                }
                if name in addrs:
                    for addr in addrs[name]:
                        if addr.family == sock_module.AF_INET:
                            iface["ip"] = addr.address
                            iface["netmask"] = addr.netmask
                        elif hasattr(sock_module, "AF_PACKET") and addr.family == sock_module.AF_PACKET:
                            iface["mac"] = addr.address
                        # Windows: psutil uses AF_LINK (psutil.AF_LINK) for MAC
                        elif addr.family == getattr(psutil, "AF_LINK", -1):
                            iface["mac"] = addr.address
                interfaces.append(iface)

            # 获取默认网关
            gateways = psutil.net_if_addrs()
            gw_output = run_command("ip route show default 2>/dev/null || route -n 2>/dev/null", timeout=5)
            if gw_output:
                for line in gw_output.split("\n"):
                    if "default" in line or "0.0.0.0" in line:
                        parts = line.split()
                        for i, part in enumerate(parts):
                            if part == "via" and i + 1 < len(parts):
                                for iface in interfaces:
                                    if not iface["gateway"]:
                                        iface["gateway"] = parts[i + 1]
                                break
        except ImportError:
            pass
        return interfaces

    def _get_dns_cache(self) -> list:
        """获取 DNS 缓存."""
        dns_cache = []
        if is_windows():
            output = run_command("ipconfig /displaydns", timeout=15)
            if output:
                current: dict[str, Any] = {}
                for line in output.split("\n"):
                    line = line.strip()
                    if line.startswith("Record Name") or line.startswith("记录名称"):
                        if current:
                            dns_cache.append(current)
                        current = {"domain": line.split(":", 1)[-1].strip() if ":" in line else "",
                                   "type": "", "value": "", "ttl": 0}
                    elif line.startswith("Record Type") or line.startswith("记录类型"):
                        if current:
                            current["type"] = line.split(":", 1)[-1].strip() if ":" in line else ""
                    elif line.startswith("Record Data") or line.startswith("记录数据"):
                        if current:
                            current["value"] = line.split(":", 1)[-1].strip() if ":" in line else ""
                    elif "TTL" in line or "生存时间" in line:
                        if current:
                            try:
                                ttl_str = line.split(":", 1)[-1].strip() if ":" in line else "0"
                                current["ttl"] = int(ttl_str)
                            except ValueError:
                                current["ttl"] = 0
                if current:
                    dns_cache.append(current)
        return dns_cache

    def _get_hosts_file(self) -> str:
        """获取 hosts 文件内容."""
        if is_windows():
            import os
            hosts_path = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                                       "System32", "drivers", "etc", "hosts")
        else:
            hosts_path = "/etc/hosts"
        content = read_file_safe(hosts_path)
        return content or ""

    def _get_routing_table(self) -> list:
        """获取路由表."""
        routes = []
        if is_windows():
            output = run_command("route print -4 2>nul", timeout=10)
            if output:
                in_table = False
                for line in output.split("\n"):
                    if "Active Routes" in line or "活动路由" in line:
                        in_table = True
                        continue
                    if in_table:
                        if line.strip().startswith("=") or "Default" in line or not line.strip():
                            if in_table and routes:
                                break
                            continue
                        parts = line.split()
                        if len(parts) >= 5 and parts[0] != "Network":
                            try:
                                routes.append({
                                    "destination": parts[0],
                                    "gateway": parts[2],
                                    "interface": parts[3],
                                    "metric": int(parts[4]) if len(parts) > 4 else 0,
                                })
                            except (ValueError, IndexError):
                                continue
        elif is_linux():
            output = run_command("ip route show 2>/dev/null || route -n 2>/dev/null", timeout=10)
            if output:
                for line in output.split("\n"):
                    parts = line.split()
                    if not parts:
                        continue
                    if parts[0] == "default":
                        gateway = parts[2] if len(parts) > 2 else ""
                        interface = parts[4] if len(parts) > 4 else ""
                        routes.append({
                            "destination": "0.0.0.0",
                            "gateway": gateway,
                            "interface": interface,
                            "metric": 0,
                        })
                    elif len(parts) >= 2:
                        routes.append({
                            "destination": parts[0],
                            "gateway": "",
                            "interface": parts[2] if len(parts) > 2 else "",
                            "metric": 0,
                        })
        return routes
