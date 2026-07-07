"""主机画像构建器 — 从采集数据提取主机画像."""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class ProfileBuilder:
    """主机画像构建器."""

    @staticmethod
    def build(raw_data: dict) -> dict:
        """从采集数据构建主机画像.

        Args:
            raw_data: Agent JSON 数据.

        Returns:
            主机画像字典，包含各字段的 JSON 字符串.
        """
        system_info = raw_data.get("system_info", {})
        if not isinstance(system_info, dict):
            system_info = {}

        users = raw_data.get("users", [])
        if not isinstance(users, list):
            users = []

        security = raw_data.get("security", {})
        if not isinstance(security, dict):
            security = {}

        network = raw_data.get("network", {})
        if not isinstance(network, dict):
            network = {}

        # CPU 信息
        cpu_info = system_info.get("cpu", {})
        if isinstance(cpu_info, dict):
            cpu_info_str = json.dumps(cpu_info, ensure_ascii=False)
        else:
            cpu_info_str = json.dumps({"model": str(cpu_info)}, ensure_ascii=False)

        # 内存信息
        memory_info = system_info.get("memory", {})
        if isinstance(memory_info, dict):
            memory_info_str = json.dumps(memory_info, ensure_ascii=False)
        else:
            memory_info_str = json.dumps({"info": str(memory_info)}, ensure_ascii=False)

        # 磁盘信息
        disks = system_info.get("disks", [])
        if isinstance(disks, list):
            disk_info_str = json.dumps(disks, ensure_ascii=False)
        else:
            disk_info_str = json.dumps([], ensure_ascii=False)

        # 网络接口信息
        interfaces = network.get("interfaces", [])
        if isinstance(interfaces, list):
            network_info_str = json.dumps(interfaces, ensure_ascii=False)
        else:
            network_info_str = json.dumps([], ensure_ascii=False)

        # 已安装软件（从 services 或 security 获取）
        installed_software = []
        services = raw_data.get("services", [])
        if isinstance(services, list):
            for svc in services:
                if isinstance(svc, dict):
                    installed_software.append({
                        "name": svc.get("name", ""),
                        "display_name": svc.get("display_name", ""),
                        "status": svc.get("status", ""),
                    })
        installed_software_str = json.dumps(installed_software, ensure_ascii=False)

        # 用户账户
        user_accounts = []
        if isinstance(users, list):
            for user in users:
                if isinstance(user, dict):
                    user_accounts.append({
                        "username": user.get("username", ""),
                        "uid": user.get("uid"),
                        "is_admin": user.get("is_admin", False),
                        "is_disabled": user.get("is_disabled", False),
                        "last_logon": user.get("last_logon", ""),
                    })
        user_accounts_str = json.dumps(user_accounts, ensure_ascii=False)

        # 安全产品
        antivirus = security.get("antivirus", [])
        security_products = []
        if isinstance(antivirus, list):
            for av in antivirus:
                if isinstance(av, dict):
                    security_products.append({
                        "name": av.get("name", av.get("displayName", "")),
                        "status": av.get("status", ""),
                    })
        security_products_str = json.dumps(security_products, ensure_ascii=False)

        # 系统摘要
        system_summary = {
            "hostname": system_info.get("hostname", ""),
            "os": system_info.get("os", ""),
            "os_version": system_info.get("os_version", ""),
            "architecture": system_info.get("architecture", ""),
            "uptime_seconds": system_info.get("uptime_seconds", 0),
            "timezone": system_info.get("timezone", ""),
            "install_date": system_info.get("install_date", ""),
        }
        system_summary_str = json.dumps(system_summary, ensure_ascii=False)

        return {
            "cpu_info": cpu_info_str,
            "memory_info": memory_info_str,
            "disk_info": disk_info_str,
            "network_info": network_info_str,
            "installed_software": installed_software_str,
            "user_accounts": user_accounts_str,
            "security_products": security_products_str,
            "system_summary": system_summary_str,
        }
