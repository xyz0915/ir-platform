"""主机 CRUD 接口."""

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.schemas.host import HostCreate
from app.services.auth_service import get_current_user
from app.services.case_service import CaseService
from app.services.host_service import HostService

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/cases/{case_id}/hosts")
def list_hosts(case_id: int, current_user: dict = Depends(get_current_user)):
    """获取案件下的主机列表."""
    case = CaseService.get_case(case_id)
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="案件不存在",
        )
    hosts = HostService.list_hosts(case_id)
    return {"code": 0, "data": hosts, "message": "success"}


@router.post("/cases/{case_id}/hosts")
def create_host(
    case_id: int,
    host: HostCreate,
    current_user: dict = Depends(get_current_user),
):
    """添加主机到案件."""
    case = CaseService.get_case(case_id)
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="案件不存在",
        )
    result = HostService.create_host(
        case_id=case_id,
        hostname=host.hostname,
        ip_address=host.ip_address,
        os_type=host.os_type,
        os_version=host.os_version,
    )
    return {"code": 0, "data": result, "message": "success"}


@router.get("/hosts/{host_id}")
def get_host(host_id: int, current_user: dict = Depends(get_current_user)):
    """获取主机详情."""
    host = HostService.get_host(host_id)
    if not host:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="主机不存在",
        )
    return {"code": 0, "data": host, "message": "success"}


@router.delete("/hosts/{host_id}")
def delete_host(host_id: int, current_user: dict = Depends(get_current_user)):
    """删除主机."""
    host = HostService.get_host(host_id)
    if not host:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="主机不存在",
        )
    HostService.delete_host(host_id)
    return {"code": 0, "data": {"success": True}, "message": "success"}
