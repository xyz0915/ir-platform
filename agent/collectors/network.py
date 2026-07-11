"""6. 网络信息采集器."""

import json as _json
import logging
import socket
from typing import Any

from collectors.base_collector import BaseCollector
from utils.platform import is_windows, is_linux, run_command, read_file_safe, get_timestamp

logger = logging.getLogger(__name__)


class NetworkCollector(BaseCollector):
    """网络信息采集器.

    采集网络连接、网卡接口、DNS 缓存、hosts 文件、路由表、
    以及平台所需的扁平化 network_connections 列表.
    """

    name = "network"
    platform = ["windows", "linux"]

    def collect(self) -> dict:
        """执行网络信息采集."""
        raw_connections = self._get_connections()
        windows_conn = self._collect_windows_connections()
        result: dict[str, Any] = {
            "connections": raw_connections,
            "interfaces": self._get_interfaces(),
            "dns_cache": self._get_dns_cache(),
            "hosts_file": self._get_hosts_file(),
            "routing_table": self._get_routing_table(),
            "network_connections": self._build_network_connections(raw_connections),
            "tcp_connections": windows_conn.get("tcp_connections", []),
            "udp_endpoints": windows_conn.get("udp_endpoints", []),
        }
        return result

    # ------------------------------------------------------------------
    # Windows 进程级网络连接采集 (PowerShell)
    # ------------------------------------------------------------------

    def _collect_windows_connections(self) -> dict[str, list]:
        """采集 Windows 进程级 TCP/UDP 连接及 DNS 缓存.

        使用 PowerShell Get-NetTCPConnection / Get-NetUDPEndpoint 获取
        进程级连接详情，以及 ipconfig /displaydns 获取 DNS 解析缓存。

        所有子采集独立 try/except，单项失败不影响其他项，
        整体异常时返回空列表，不崩整个采集流程。

        Returns:
            {"tcp_connections": [...], "udp_endpoints": [...], "dns_cache": [...]}
        """
        result: dict[str, list] = {
            "tcp_connections": [],
            "udp_endpoints": [],
            "dns_cache": [],
        }

        if not is_windows():
            return result

        # ---- TCP 连接 ----
        try:
            ps_cmd = (
                'powershell -NoProfile -Command '
                '"& { Get-NetTCPConnection | '
                'Select-Object LocalAddress,LocalPort,RemoteAddress,RemotePort,State,OwningProcess | '
                'ConvertTo-Json -Compress }"'
            )
            output = run_command(ps_cmd, timeout=30)
            if output:
                data = _json.loads(output)
                if isinstance(data, dict):
                    data = [data]
                for conn in data or []:
                    result["tcp_connections"].append({
                        "local_address": str(conn.get("LocalAddress", "")),
                        "local_port": int(conn.get("LocalPort", 0)),
                        "remote_address": str(conn.get("RemoteAddress", "")),
                        "remote_port": int(conn.get("RemotePort", 0)),
                        "state": str(conn.get("State", "")),
                        "owning_process": int(conn.get("OwningProcess", 0)),
                    })
                logger.info(
                    "Collected %d TCP connections via PowerShell",
                    len(result["tcp_connections"]),
                )
        except Exception as exc:
            logger.warning("Failed to collect PowerShell TCP connections: %s", exc)

        # ---- UDP 端点 ----
        try:
            ps_cmd = (
                'powershell -NoProfile -Command '
                '"& { Get-NetUDPEndpoint | '
                'Select-Object LocalAddress,LocalPort,OwningProcess | '
                'ConvertTo-Json -Compress }"'
            )
            output = run_command(ps_cmd, timeout=30)
            if output:
                data = _json.loads(output)
                if isinstance(data, dict):
                    data = [data]
                for ep in data or []:
                    result["udp_endpoints"].append({
                        "local_address": str(ep.get("LocalAddress", "")),
                        "local_port": int(ep.get("LocalPort", 0)),
                        "owning_process": int(ep.get("OwningProcess", 0)),
                    })
                logger.info(
                    "Collected %d UDP endpoints via PowerShell",
                    len(result["udp_endpoints"]),
                )
        except Exception as exc:
            logger.warning("Failed to collect PowerShell UDP endpoints: %s", exc)

        # ---- DNS 缓存 (ipconfig /displaydns) ----
        try:
            dns_output = run_command("ipconfig /displaydns", timeout=15)
            if dns_output:
                current: dict[str, Any] = {}
                for line in dns_output.split("\n"):
                    line = line.strip()
                    if line.startswith("Record Name") or line.startswith("记录名称"):
                        if current:
                            result["dns_cache"].append(current)
                        current = {
                            "domain": line.split(":", 1)[-1].strip() if ":" in line else "",
                            "type": "",
                            "value": "",
                            "ttl": 0,
                        }
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
                    result["dns_cache"].append(current)
                logger.info(
                    "Collected %d DNS cache entries via ipconfig /displaydns",
                    len(result["dns_cache"]),
                )
        except Exception as exc:
            logger.warning("Failed to collect DNS cache via ipconfig /displaydns: %s", exc)

        return result

    # ------------------------------------------------------------------
    # 连接列表构建
    # ------------------------------------------------------------------

    def _build_network_connections(self, connections: list) -> list:
        """将内部连接列表映射为平台 network_connections 表所需格式.

        字段映射:
            local_address → local_addr
            remote_address → remote_addr
            status → state
        补充 protocol / pid / process_name / collected_at.
        """
        now = get_timestamp()
        result = []
        for conn in connections:
            result.append({
                "protocol": conn.get("protocol", ""),
                "local_addr": conn.get("local_address", ""),
                "local_port": conn.get("local_port", 0),
                "remote_addr": conn.get("remote_address", ""),
                "remote_port": conn.get("remote_port", 0),
                "state": conn.get("state", ""),
                "pid": conn.get("pid", 0),
                "process_name": conn.get("process_name", ""),
                "collected_at": now,
            })
        return result

    def _get_connections(self) -> list:
        """获取网络连接列表（psutil 优先，失败回退 netstat）."""
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
            if not connections:
                connections = self._get_connections_netstat()
        except ImportError:
            connections = self._get_connections_netstat()
        return connections

    def _get_connections_netstat(self) -> list:
        """使用 netstat -ano 作为 Windows 回退方案."""
        from utils.platform import run_command
        connections = []
        if not is_windows():
            return connections
        output = run_command("netstat -ano", timeout=15)
        if output:
            for line in output.split("\n"):
                parts = line.split()
                if len(parts) < 5:
                    continue
                proto = parts[0].upper()
                if proto not in ("TCP", "UDP"):
                    continue
                local = parts[1]
                remote = parts[2]
                state = parts[3] if proto == "TCP" else "LISTEN"
                pid_str = parts[-1] if proto == "UDP" else (
                    parts[4] if len(parts) >= 5 and parts[4].isdigit() else "0"
                )
                # 对于 TCP LISTENING → ESTABLISHED 多词状态
                if proto == "TCP" and not pid_str.isdigit():
                    # 找最后那个纯数字字段
                    for p in reversed(parts):
                        if p.isdigit():
                            pid_str = p
                            break
                try:
                    pid = int(pid_str)
                except ValueError:
                    pid = 0

                la, lp = _split_addr(local)
                ra, rp = _split_addr(remote)

                connections.append({
                    "protocol": proto,
                    "local_address": la, "local_port": lp,
                    "remote_address": ra, "remote_port": rp,
                    "state": state,
                    "pid": pid, "process_name": "",
                })
        return connections

    def _get_interfaces(self) -> list:
        """获取网卡接口信息（psutil 优先，失败回退 ipconfig）."""
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
                        elif addr.family == getattr(psutil, "AF_LINK", -1):
                            iface["mac"] = addr.address
                interfaces.append(iface)

            if not interfaces:
                interfaces = self._get_interfaces_fallback()
        except ImportError:
            interfaces = self._get_interfaces_fallback()
        return interfaces

    def _get_interfaces_fallback(self) -> list:
        """使用 ipconfig 作为 Windows 网卡回退方案."""
        interfaces = []
        if not is_windows():
            return interfaces
        output = run_command("ipconfig /all", timeout=15)
        if output:
            current: dict[str, Any] = {}
            for line in output.split("\n"):
                line = line.strip()
                if not line:
                    if current:
                        interfaces.append(current)
                        current = {}
                    continue
                # 检测新适配器段
                if "adapter" in line.lower() and ":" in line:
                    if current:
                        interfaces.append(current)
                    name = line.split(":")[-1].strip().rstrip(":")
                    current = {"name": name or line, "ip": "", "mac": "", "netmask": "", "gateway": "", "isup": True, "speed": 0}
                    continue
                if not current:
                    current = {"name": "", "ip": "", "mac": "", "netmask": "", "gateway": "", "isup": True, "speed": 0}
                lower = line.lower()
                parts = line.split(":", 1)
                val = parts[1].strip() if len(parts) > 1 else ""
                if "physical" in lower:
                    current["mac"] = val
                elif "ipv4" in lower and "address" in lower:
                    current["ip"] = val.split("(")[0].strip()
                elif "subnet" in lower:
                    current["netmask"] = val
                elif "default gateway" in lower:
                    current["gateway"] = val
            if current:
                interfaces.append(current)
        return [i for i in interfaces if i.get("name")]

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


def _split_addr(addr: str) -> tuple:
    """拆分 '192.168.1.1:80' 为 ('192.168.1.1', 80)."""
    if ":" in addr:
        # IPv4 或 [IPv6]:port
        if addr.startswith("["):
            host, rest = addr[1:].split("]", 1)
            port_str = rest.lstrip(":")
            try:
                return host, int(port_str)
            except ValueError:
                return host, 0
        else:
            host, port_str = addr.rsplit(":", 1)
            try:
                return host, int(port_str)
            except ValueError:
                return addr, 0
    return addr, 0
