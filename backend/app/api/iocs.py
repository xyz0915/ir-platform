"""IOC 管理接口（T-P1-4）.

仅管理 IOC 指标（入库/查询/删除/批量导入），不参与引擎匹配逻辑。
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.models.ioc import Ioc
from app.models.threat_intel import ThreatIntel
from app.schemas.analysis import (
    IocCreate,
    IocImportRequest,
    IocUpdate,
    EnrichRequest,
    EnrichBatchRequest,
)
from app.services.auth_service import get_current_user
from app.services.enrichment_service import (
    get_enrichment_service,
    UnsupportedIocTypeError,
    QuotaExceededError,
    ThreatIntelQueryError,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# 支持外联查询的 IOC 类型
_ENRICH_SUPPORTED = ("ip", "domain")


@router.get("")
def list_iocs(
    ioc_type: str = Query(None, description="按类型筛选（ip/domain/url/hash/cert）"),
    current_user: dict = Depends(get_current_user),
):
    """获取 IOC 列表."""
    items = Ioc.list(ioc_type=ioc_type)
    return {"code": 0, "data": items, "message": "success"}


@router.post("")
def create_ioc(
    ioc: IocCreate,
    current_user: dict = Depends(get_current_user),
):
    """新增单条 IOC."""
    result = Ioc.create(
        ioc_type=ioc.ioc_type,
        ioc_value=ioc.ioc_value,
        source="user",
        description=ioc.description,
        enabled=ioc.enabled,
    )
    return {"code": 0, "data": result, "message": "success"}


@router.post("/import")
def import_iocs(
    payload: IocImportRequest,
    current_user: dict = Depends(get_current_user),
):
    """批量导入 IOC（文件导入入口）."""
    items = [it.dict() for it in payload.items]
    inserted = Ioc.batch_create(items)
    return {
        "code": 0,
        "data": {"inserted": inserted, "total": len(items)},
        "message": "success",
    }


@router.delete("/{ioc_id}")
def delete_ioc(
    ioc_id: int,
    current_user: dict = Depends(get_current_user),
):
    """删除 IOC."""
    existing = Ioc.get_by_id(ioc_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="IOC 不存在",
        )
    Ioc.delete(ioc_id)
    return {"code": 0, "data": None, "message": "success"}


@router.put("/{ioc_id}")
def update_ioc(
    ioc_id: int,
    payload: IocUpdate,
    current_user: dict = Depends(get_current_user),
):
    """更新 IOC（启用开关 / 描述 / 来源）.

    仅更新 payload 中显式传入的非 None 字段，其余字段保持不变。
    前端"启用"列 el-switch 即调用此端点切换 enabled。
    """
    existing = Ioc.get_by_id(ioc_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="IOC 不存在",
        )
    updated = Ioc.update(
        ioc_id,
        enabled=payload.enabled,
        description=payload.description,
        source=payload.source,
    )
    return {"code": 0, "data": updated, "message": "success"}


@router.post("/{ioc_id}/enrich")
def enrich_ioc(
    ioc_id: int,
    payload: Optional[EnrichRequest] = None,
    current_user: dict = Depends(get_current_user),
):
    """外联查询单个 IOC 的威胁情报（仅支持 ip/domain）.

    返回结构统一 ``{code, data, message}``:
      - 200/code=0  成功
      - code=400    类型不支持（仅 ip/domain）
      - code=404    IOC 不存在
      - code=429    当日配额耗尽
      - code=500    查询异常
    """
    ioc = Ioc.get_by_id(ioc_id)
    if not ioc:
        return {"code": 404, "data": None, "message": "IOC 不存在"}
    if ioc.get("ioc_type") not in _ENRICH_SUPPORTED:
        return {
            "code": 400,
            "data": None,
            "message": f"仅支持 ip/domain 类型外联查询，当前类型: {ioc.get('ioc_type')}",
        }

    svc = get_enrichment_service()
    provider_name = payload.provider if payload else None
    try:
        record = svc.enrich_ioc(
            ioc_id, ioc["ioc_type"], ioc["ioc_value"], provider_name=provider_name
        )
    except UnsupportedIocTypeError as exc:
        return {"code": 400, "data": None, "message": str(exc)}
    except QuotaExceededError as exc:
        return {"code": 429, "data": None, "message": str(exc)}
    except ThreatIntelQueryError as exc:
        return {"code": 500, "data": None, "message": str(exc)}

    return {"code": 0, "data": record, "message": "success"}


@router.post("/enrich/batch")
def enrich_ioc_batch(
    payload: EnrichBatchRequest,
    current_user: dict = Depends(get_current_user),
):
    """批量外联查询 IOC.

    请求体: ``{ids:[...]}`` 或 ``{filter:{ioc_type?, provider?}}``。
    返回 ``{total, enriched, skipped, failed, details}``。
    """
    ioc_items: list = []
    provider_name: Optional[str] = None

    if payload.ids:
        for raw_id in payload.ids:
            try:
                iid = int(raw_id)
            except (ValueError, TypeError):
                continue
            ioc = Ioc.get_by_id(iid)
            if not ioc:
                continue
            ioc_items.append({
                "ioc_id": ioc["id"],
                "ioc_type": ioc["ioc_type"],
                "ioc_value": ioc["ioc_value"],
            })
    elif payload.filter:
        f = payload.filter or {}
        provider_name = f.get("provider")
        ioc_list = Ioc.list(ioc_type=f.get("ioc_type"))
        for ioc in ioc_list:
            ioc_items.append({
                "ioc_id": ioc["id"],
                "ioc_type": ioc["ioc_type"],
                "ioc_value": ioc["ioc_value"],
            })

    svc = get_enrichment_service()
    try:
        result = svc.enrich_batch(ioc_items, provider_name=provider_name)
    except (QuotaExceededError, ThreatIntelQueryError) as exc:
        code = 429 if isinstance(exc, QuotaExceededError) else 500
        return {"code": code, "data": None, "message": str(exc)}

    return {"code": 0, "data": result, "message": "success"}


@router.get("/{ioc_id}/threat-intel")
def get_ioc_threat_intel(
    ioc_id: int,
    current_user: dict = Depends(get_current_user),
):
    """获取某 IOC 的全部威胁情报历史（按查询时间倒序）."""
    ioc = Ioc.get_by_id(ioc_id)
    if not ioc:
        return {"code": 404, "data": None, "message": "IOC 不存在"}
    records = ThreatIntel.list_by_ioc(ioc_id)
    return {"code": 0, "data": records, "message": "success"}
