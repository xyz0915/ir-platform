"""主机业务逻辑服务."""

import logging
from typing import Optional

from app.models.host import Host

logger = logging.getLogger(__name__)


class HostService:
    """主机业务逻辑层."""

    @staticmethod
    def create_host(case_id: int, hostname: str, ip_address: Optional[str] = None,
                    os_type: Optional[str] = None, os_version: Optional[str] = None) -> dict:
        """创建主机."""
        return Host.create(
            case_id=case_id,
            hostname=hostname,
            ip_address=ip_address,
            os_type=os_type,
            os_version=os_version,
        )

    @staticmethod
    def get_host(host_id: int) -> Optional[dict]:
        """获取主机详情."""
        return Host.get_by_id(host_id)

    @staticmethod
    def list_hosts(case_id: int) -> list:
        """获取案件下的主机列表."""
        return Host.list_by_case(case_id)

    @staticmethod
    def delete_host(host_id: int) -> bool:
        """删除主机."""
        return Host.delete(host_id)

    @staticmethod
    def update_host_status(host_id: int, status: str, **kwargs) -> Optional[dict]:
        """更新主机状态."""
        return Host.update_status(host_id, status, **kwargs)
