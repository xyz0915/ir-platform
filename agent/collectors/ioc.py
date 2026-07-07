"""15. IOC 能力扫描采集器."""

import hashlib
import logging
import os
import re
from typing import Any

from collectors.base_collector import BaseCollector
from utils.platform import is_windows, is_linux

logger = logging.getLogger(__name__)

# 内置默认恶意 IOC 列表
DEFAULT_BAD_IPS = [
    "185.220.101.1", "185.220.101.2", "185.220.101.3",
    "104.244.72.115", "104.244.74.211",
    "91.219.236.166", "192.42.116.14",
    "23.94.28.183", "107.189.1.150",
]

DEFAULT_BAD_DOMAINS = [
    "malware-c2.example.com",
    "botnet-cc.example.net",
    "trojan-download.example.org",
    "phishing-site.example.com",
    "malicious-cdn.example.net",
]

DEFAULT_BAD_HASHES = [
    "44d88612fea8a8f36de82e1278abb02f",  # EICAR 测试哈希
    "275a021bbfb6489e54d471899f7db9d1663fc695ec2fe2a2c5d7f2e0c2c5b9e",
]

# IP 地址正则
IP_REGEX = re.compile(r'\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b')
# 域名正则（简化版）
DOMAIN_REGEX = re.compile(
    r'\b([a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)'
    r'+([a-zA-Z]{2,})\b'
)


class IocCollector(BaseCollector):
    """IOC 能力扫描采集器.

    扫描已知恶意 IP/域名/文件哈希（内置默认 IOC 列表）.
    """

    name = "ioc"
    platform = ["windows", "linux"]

    def collect(self) -> dict:
        """执行 IOC 扫描."""
        return {
            "known_bad_ips": DEFAULT_BAD_IPS,
            "known_bad_domains": DEFAULT_BAD_DOMAINS,
            "known_bad_hashes": DEFAULT_BAD_HASHES,
            "matched_items": self._scan_all(),
        }

    def _scan_all(self) -> list:
        """在系统数据中扫描 IOC."""
        matched = []

        # 扫描网络连接
        matched.extend(self._scan_connections())

        # 扫描 DNS 缓存
        matched.extend(self._scan_dns_cache())

        # 扫描进程
        matched.extend(self._scan_processes())

        # 扫描 hosts 文件
        matched.extend(self._scan_hosts_file())

        # 扫描可疑文件哈希
        matched.extend(self._scan_file_hashes())

        return matched

    def _scan_connections(self) -> list:
        """扫描网络连接中的恶意 IP."""
        matched = []
        try:
            import psutil
            for conn in psutil.net_connections(kind="inet"):
                remote_addr = conn.raddr.ip if conn.raddr else ""
                if remote_addr and remote_addr in DEFAULT_BAD_IPS:
                    matched.append({
                        "ioc_type": "ip",
                        "ioc_value": remote_addr,
                        "matched_in": "network_connections",
                        "context": f"PID: {conn.pid}, Local: {conn.laddr}",
                        "severity": "high",
                    })
        except ImportError:
            pass
        return matched

    def _scan_dns_cache(self) -> list:
        """扫描 DNS 缓存中的恶意域名."""
        matched = []
        # 这里仅检查 hosts 文件和已知连接
        return matched

    def _scan_processes(self) -> list:
        """扫描进程命令行中的恶意域名/IP."""
        matched = []
        try:
            import psutil
            for proc in psutil.process_iter(["pid", "name", "cmdline"]):
                try:
                    cmdline = proc.info.get("cmdline")
                    if not cmdline:
                        continue
                    cmdline_str = " ".join(cmdline)

                    # 检查恶意 IP
                    for ip in DEFAULT_BAD_IPS:
                        if ip in cmdline_str:
                            matched.append({
                                "ioc_type": "ip",
                                "ioc_value": ip,
                                "matched_in": f"process:{proc.info.get('name')}",
                                "context": f"PID: {proc.info.get('pid')}, CMD: {cmdline_str[:200]}",
                                "severity": "high",
                            })

                    # 检查恶意域名
                    for domain in DEFAULT_BAD_DOMAINS:
                        if domain in cmdline_str:
                            matched.append({
                                "ioc_type": "domain",
                                "ioc_value": domain,
                                "matched_in": f"process:{proc.info.get('name')}",
                                "context": f"PID: {proc.info.get('pid')}, CMD: {cmdline_str[:200]}",
                                "severity": "high",
                            })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except ImportError:
            pass
        return matched

    def _scan_hosts_file(self) -> list:
        """扫描 hosts 文件中的恶意域名/IP."""
        matched = []
        from utils.platform import read_file_safe, is_windows
        import os

        if is_windows():
            hosts_path = os.path.join(
                os.environ.get("SystemRoot", r"C:\Windows"),
                "System32", "drivers", "etc", "hosts"
            )
        else:
            hosts_path = "/etc/hosts"

        content = read_file_safe(hosts_path)
        if content:
            for ip in DEFAULT_BAD_IPS:
                if ip in content:
                    matched.append({
                        "ioc_type": "ip",
                        "ioc_value": ip,
                        "matched_in": "hosts_file",
                        "context": f"Found in {hosts_path}",
                        "severity": "medium",
                    })
            for domain in DEFAULT_BAD_DOMAINS:
                if domain in content:
                    matched.append({
                        "ioc_type": "domain",
                        "ioc_value": domain,
                        "matched_in": "hosts_file",
                        "context": f"Found in {hosts_path}",
                        "severity": "medium",
                    })
        return matched

    def _scan_file_hashes(self) -> list:
        """扫描可疑路径下文件的哈希."""
        matched = []
        scan_dirs = []

        if is_windows():
            scan_dirs = [
                os.environ.get("TEMP", ""),
                r"C:\Users\Public",
                r"C:\Windows\Temp",
            ]
        else:
            scan_dirs = ["/tmp", "/var/tmp", "/dev/shm"]

        for scan_dir in scan_dirs:
            if not scan_dir or not os.path.exists(scan_dir):
                continue
            try:
                for root, dirs, files in os.walk(scan_dir):
                    depth = root[len(scan_dir):].count(os.sep)
                    if depth >= 2:
                        dirs[:] = []
                        continue
                    for filename in files:
                        filepath = os.path.join(root, filename)
                        _, ext = os.path.splitext(filename)
                        if ext.lower() in [".exe", ".dll", ".bat", ".ps1", ".vbs", ".scr"]:
                            file_hash = self._compute_file_hash(filepath)
                            if file_hash and file_hash in DEFAULT_BAD_HASHES:
                                matched.append({
                                    "ioc_type": "hash",
                                    "ioc_value": file_hash,
                                    "matched_in": "file",
                                    "context": filepath,
                                    "severity": "critical",
                                })
            except (PermissionError, OSError):
                continue
        return matched

    def _compute_file_hash(self, filepath: str) -> str:
        """计算文件 MD5 哈希."""
        try:
            hash_md5 = hashlib.md5()
            with open(filepath, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    hash_md5.update(chunk)
            return hash_md5.hexdigest()
        except (IOError, OSError, PermissionError):
            return ""
