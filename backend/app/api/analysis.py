"""分析接口 — 触发分析与查询分析结果."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from app.services.analysis_service import AnalysisService
from app.services.auth_service import get_current_user
from app.services.host_service import HostService
from app.services.import_service import ImportService
from app.services.sync_service import SyncService

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
        # 常驻 daemon 主机：有已注册 Agent 或实时进程事件亦允许触发分析
        from app.models.agent_model import AgentModel
        from app.models.process_event import ProcessEvent

        agent_registered = AgentModel.get_token_status(host_id).get("token_set")
        has_events = bool(ProcessEvent.list_by_host(host_id))
        if not agent_registered and not has_events:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="主机尚未导入采集数据，且无在线 Agent / 实时进程事件，无法分析",
            )
    try:
        # 1. 主机分析
        result = AnalysisService.analyze(host_id)
        # 2. 分析完成后自动同步 CM 数据到分析中心
        try:
            sync_result = SyncService.sync_cm_to_ac(host_id)
            result["sync"] = {
                "total_cm_rows": sync_result.get("total_cm_rows", 0),
                "synced": sync_result.get("synced", 0),
            }
            if sync_result["synced"]:
                logger.info("分析后自动同步: host=%d synced=%d", host_id, sync_result["synced"])
        except Exception as sync_exc:
            logger.warning("分析后同步 CM 数据失败 host=%d: %s", host_id, sync_exc)
            result["sync"] = {"error": str(sync_exc)}
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
    event_type: Optional[str] = Query(None, description="事件类型（单值，向后兼容）"),
    event_types: Optional[str] = Query(None, description="事件类型（逗号分隔多值），如 process,network"),
    severity: Optional[str] = Query(None, description="严重度（逗号分隔多值），如 high,medium"),
    ioc_hit: Optional[bool] = Query(None, description="仅返回 IOC 命中事件"),
    current_user: dict = Depends(get_current_user),
):
    """获取时间线事件."""
    result = AnalysisService.get_timeline(
        host_id, start, end, event_type,
        severities=severity, event_types=event_types, ioc_hit=ioc_hit,
    )
    return {"code": 0, "data": result, "message": "success"}


@router.get("/hosts/{host_id}/timeline/stats")
def get_timeline_stats(host_id: int, current_user: dict = Depends(get_current_user)):
    """获取时间线事件统计摘要."""
    result = AnalysisService.get_timeline_stats(host_id)
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

@router.post("/hosts/{host_id}/suspicious-connections/enrich")
def enrich_suspicious_connections(host_id: int, current_user: dict = Depends(get_current_user)):
    """一键威胁情报检测：对主机所有可疑外连的公网 IP 做 enrichment.

    - 200/code=0  成功，返回统计 ``{total, public, enriched, malicious, suspicious, skipped_private, errors}``。
    - 404          主机不存在。
    - 500          检测过程异常。
    """
    host = HostService.get_host(host_id)
    if not host:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="主机不存在",
        )
    try:
        stats = AnalysisService.enrich_suspicious_connections(host_id)
        return {"code": 0, "data": stats, "message": "success"}
    except Exception as exc:
        logger.exception("一键威胁情报检测失败 for host %d", host_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"一键威胁情报检测失败: {exc}",
        )


@router.get("/hosts/{host_id}/abnormal-processes")
def get_abnormal_processes(host_id: int, current_user: dict = Depends(get_current_user)):
    """获取异常进程列表."""
    result = AnalysisService.get_abnormal_processes(host_id)
    return {"code": 0, "data": result, "message": "success"}


@router.get("/hosts/{host_id}/process-tree")
def get_process_tree(
    host_id: int,
    enrich: bool = Query(False, description="是否返回增强字段（severity/parent_name/connections/攻击链等）。缺省为 False，响应与历史版本逐字段一致"),
    current_user: dict = Depends(get_current_user),
):
    """获取进程树结构.

    - ``enrich`` 缺省 / 为 0 / false → 响应与历史版本逐字段一致，旧前端兼容。
    - ``enrich=1`` / ``enrich=true`` → 节点 dict 增量追加增强字段（旧字段不变）。
    """
    result = AnalysisService.get_process_tree(host_id, enrich=enrich)
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


@router.post("/hosts/{host_id}/network-connections/enrich")
def enrich_network_connections(host_id: int, current_user: dict = Depends(get_current_user)):
    """对网络连接的公网 IP 做一键威胁情报检测."""
    host = HostService.get_host(host_id)
    if not host:
        raise HTTPException(status_code=404, detail="主机不存在")
    try:
        result = AnalysisService.enrich_network_connections(host_id)
        return {"code": 0, "data": result, "message": "success"}
    except Exception as e:
        logger.exception("enrich_network_connections error")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/hosts/{host_id}/network-connections")
def get_network_connections(host_id: int, current_user: dict = Depends(get_current_user)):
    """获取网络连接列表（数据采集增强 P1-2）."""
    result = AnalysisService.get_network_connections(host_id)
    return {"code": 0, "data": result, "message": "success"}


@router.get("/hosts/{host_id}/file-hashes")
def get_file_hashes(host_id: int, current_user: dict = Depends(get_current_user)):
    """获取文件哈希列表（数据采集增强 P1-3）."""
    result = AnalysisService.get_file_hashes(host_id)
    return {"code": 0, "data": result, "message": "success"}


@router.get("/hosts/{host_id}/wmi-subscriptions")
def get_wmi_subscriptions(host_id: int, current_user: dict = Depends(get_current_user)):
    """获取 WMI 订阅列表（数据采集增强 P1-5）."""
    result = AnalysisService.get_wmi_subscriptions(host_id)
    return {"code": 0, "data": result, "message": "success"}


@router.get("/hosts/{host_id}/registry-keys")
def get_registry_keys(host_id: int, current_user: dict = Depends(get_current_user)):
    """获取注册表键值列表（数据采集增强 P1-6）."""
    result = AnalysisService.get_registry_keys(host_id)
    return {"code": 0, "data": result, "message": "success"}


# ── V3-2: 事件状态更新 ──
@router.patch("/analysis/timeline/{event_id}")
def update_timeline_event(
    event_id: int,
    body: dict,
    current_user: dict = Depends(get_current_user),
):
    """更新时间线事件处置状态."""
    try:
        result = AnalysisService.update_timeline_event(event_id, body)
        return {"code": 0, "data": result, "message": "success"}
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )


# ── V3-4: 多主机时间线对比 ──
@router.get("/analysis/timeline/compare")
def compare_timelines(
    host_ids: str = Query(..., description="逗号分隔的主机ID列表，如 1,2,3"),
    current_user: dict = Depends(get_current_user),
):
    """多主机时间线叠加对比."""
    try:
        ids = [int(hid.strip()) for hid in host_ids.split(",") if hid.strip()]
        if not ids:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="host_ids 不能为空")
        if len(ids) > 5:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="最多支持 5 台主机对比")
        result = AnalysisService.compare_timelines(ids)
        return {"code": 0, "data": result, "message": "success"}
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="host_ids 格式错误")


# ── V3-5: CSV 导出 ──
@router.get("/analysis/timeline/{host_id}/export/csv")
def export_timeline_csv(
    host_id: int,
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    event_types: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """导出时间线为 CSV 文件."""
    try:
        csv_content, filename = AnalysisService.export_timeline_csv(
            host_id, start=start, end=end,
            event_types=event_types, severity=severity,
        )
        return StreamingResponse(
            iter([csv_content]),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as exc:
        logger.exception("CSV export failed for host %d", host_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"CSV 导出失败: {exc}",
        )


# ── V3-5: PDF 导出 ──
@router.get("/analysis/timeline/{host_id}/export/pdf")
def export_timeline_pdf(
    host_id: int,
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """导出时间线为 PDF 报告."""
    try:
        pdf_bytes = AnalysisService.export_timeline_pdf(host_id, start=start, end=end)
        return StreamingResponse(
            iter([pdf_bytes]),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="timeline_{host_id}.pdf"'},
        )
    except Exception as exc:
        logger.exception("PDF export failed for host %d", host_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"PDF 导出失败: {exc}",
        )


@router.get("/hosts/{host_id}/service-risk")
def get_service_risk(host_id: int, current_user: dict = Depends(get_current_user)):
    """获取主机系统服务风险分析（P0-3）."""
    result = AnalysisService.get_service_risk(host_id)
    if result is None:
        raise HTTPException(status_code=404, detail="未找到该主机的采集数据")
    return {"code": 0, "data": result, "message": "success"}
