"""分析接口 — 触发分析与查询分析结果."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.services.analysis_service import AnalysisService
from app.services.auth_service import get_current_user
from app.services.host_service import HostService
from app.services.import_service import ImportService

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/hosts/{host_id}/analyze")
def analyze_host(host_id: int, current_user: dict = Depends(get_current_user)):
    """触发主机分析."""
    host = HostService.get_host(host_id)
    if not host:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="主机不存在",
        )
    if host.get("status") not in ("imported", "analyzed"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="主机尚未导入采集数据，无法分析",
        )
    try:
        result = AnalysisService.analyze(host_id)
        return {"code": 0, "data": result, "message": "success"}
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except Exception as exc:
        logger.exception("Analysis failed for host %d", host_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"分析失败: {exc}",
        )


@router.get("/hosts/{host_id}/analysis")
def get_analysis(host_id: int, current_user: dict = Depends(get_current_user)):
    """获取分析结果汇总."""
    result = AnalysisService.get_analysis(host_id)
    return {"code": 0, "data": result, "message": "success"}


@router.get("/hosts/{host_id}/profile")
def get_profile(host_id: int, current_user: dict = Depends(get_current_user)):
    """获取主机画像."""
    result = AnalysisService.get_profile(host_id)
    return {"code": 0, "data": result, "message": "success"}


@router.get("/hosts/{host_id}/timeline")
def get_timeline(
    host_id: int,
    start: Optional[str] = Query(None, description="开始时间"),
    end: Optional[str] = Query(None, description="结束时间"),
    event_type: Optional[str] = Query(None, description="事件类型"),
    current_user: dict = Depends(get_current_user),
):
    """获取时间线事件."""
    result = AnalysisService.get_timeline(host_id, start, end, event_type)
    return {"code": 0, "data": result, "message": "success"}


@router.get("/hosts/{host_id}/ioc-hits")
def get_ioc_hits(host_id: int, current_user: dict = Depends(get_current_user)):
    """获取 IOC 命中列表."""
    result = AnalysisService.get_ioc_hits(host_id)
    return {"code": 0, "data": result, "message": "success"}


@router.get("/hosts/{host_id}/persistence")
def get_persistence(host_id: int, current_user: dict = Depends(get_current_user)):
    """获取持久化痕迹列表."""
    result = AnalysisService.get_persistence(host_id)
    return {"code": 0, "data": result, "message": "success"}


@router.get("/hosts/{host_id}/suspicious-connections")
def get_suspicious_connections(host_id: int, current_user: dict = Depends(get_current_user)):
    """获取可疑外连列表."""
    result = AnalysisService.get_suspicious_connections(host_id)
    return {"code": 0, "data": result, "message": "success"}


@router.get("/hosts/{host_id}/abnormal-processes")
def get_abnormal_processes(host_id: int, current_user: dict = Depends(get_current_user)):
    """获取异常进程列表."""
    result = AnalysisService.get_abnormal_processes(host_id)
    return {"code": 0, "data": result, "message": "success"}


@router.get("/hosts/{host_id}/process-tree")
def get_process_tree(host_id: int, current_user: dict = Depends(get_current_user)):
    """获取进程树结构."""
    result = AnalysisService.get_process_tree(host_id)
    return {"code": 0, "data": result, "message": "success"}


@router.get("/hosts/{host_id}/startup-items")
def get_startup_items(host_id: int, current_user: dict = Depends(get_current_user)):
    """获取可疑启动项列表."""
    result = AnalysisService.get_startup_items(host_id)
    return {"code": 0, "data": result, "message": "success"}


@router.get("/hosts/{host_id}/users")
def get_users(host_id: int, current_user: dict = Depends(get_current_user)):
    """获取用户账户列表."""
    raw_data = ImportService.read_raw_json(host_id)
    return {"code": 0, "data": raw_data.get("users", []) if raw_data else [], "message": "success"}


@router.get("/hosts/{host_id}/services")
def get_services(host_id: int, current_user: dict = Depends(get_current_user)):
    """获取系统服务列表."""
    raw_data = ImportService.read_raw_json(host_id)
    return {"code": 0, "data": raw_data.get("services", []) if raw_data else [], "message": "success"}


@router.get("/hosts/{host_id}/usb")
def get_usb(host_id: int, current_user: dict = Depends(get_current_user)):
    """获取USB设备记录."""
    raw_data = ImportService.read_raw_json(host_id)
    if not raw_data:
        return {"code": 0, "data": [], "message": "success"}
    usb_data = raw_data.get("usb", {})
    if isinstance(usb_data, dict):
        return {"code": 0, "data": usb_data.get("devices", []), "message": "success"}
    return {"code": 0, "data": usb_data if isinstance(usb_data, list) else [], "message": "success"}


@router.get("/hosts/{host_id}/remote-control")
def get_remote_control(host_id: int, current_user: dict = Depends(get_current_user)):
    """获取远程工具记录."""
    raw_data = ImportService.read_raw_json(host_id)
    return {"code": 0, "data": raw_data.get("remote_control", []) if raw_data else [], "message": "success"}
