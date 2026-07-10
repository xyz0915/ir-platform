"""威胁情报外联（Enrichment）配置管理接口.

挂载前缀: ``/api/threat-intel``

端点:
  - GET  /providers      列出全部 provider（剔除 api_key_ref，不泄露密钥引用）
  - POST /providers      新增/更新 provider（按 name upsert）
  - PUT  /providers      更新 provider（按 name upsert）
  - GET  /settings       获取运行策略
  - PUT  /settings       更新运行策略

统一返回结构: ``{code, data, message}``
"""

import logging

from fastapi import APIRouter, Depends, status
from fastapi.exceptions import HTTPException

from app.models.threat_intel import ThreatIntelProviderConfig, EnrichSettings as EnrichSettingsModel
from app.schemas.analysis import (
    ProviderConfig,
    ProviderConfigInput,
    EnrichSettings,
)
from app.services.auth_service import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()


def _to_provider_config_view(provider: dict) -> ProviderConfig:
    """将存储的 provider dict 转为对外视图（剔除 api_key_ref）."""
    return ProviderConfig(
        name=provider.get("name", ""),
        type=provider.get("type", "threatbook"),
        base_url=provider.get("base_url", ""),
        enabled=bool(provider.get("enabled", True)),
        rate_limit_qps=int(provider.get("rate_limit_qps", 2)),
        endpoints=provider.get("endpoints") or {},
    )


@router.get("/providers")
def list_providers(current_user: dict = Depends(get_current_user)):
    """列出全部 provider（不返回 api_key_ref）."""
    providers = ThreatIntelProviderConfig.load()
    data = [_to_provider_config_view(p) for p in providers]
    return {"code": 0, "data": data, "message": "success"}


@router.post("/providers")
def create_provider(
    payload: ProviderConfigInput,
    current_user: dict = Depends(get_current_user),
):
    """新增或更新一个 provider（按 name upsert）."""
    try:
        saved = ThreatIntelProviderConfig.upsert(payload.dict(exclude_none=False))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return {"code": 0, "data": _to_provider_config_view(saved), "message": "success"}


@router.put("/providers")
def update_provider(
    payload: ProviderConfigInput,
    current_user: dict = Depends(get_current_user),
):
    """更新一个 provider（按 name upsert，与 POST 行为一致）."""
    try:
        saved = ThreatIntelProviderConfig.upsert(payload.dict(exclude_none=False))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return {"code": 0, "data": _to_provider_config_view(saved), "message": "success"}


@router.get("/settings")
def get_settings(current_user: dict = Depends(get_current_user)):
    """获取运行策略."""
    data = EnrichSettingsModel.load()
    return {"code": 0, "data": EnrichSettings(**data), "message": "success"}


@router.put("/settings")
def update_settings(
    payload: EnrichSettings,
    current_user: dict = Depends(get_current_user),
):
    """更新运行策略（仅白名单字段）."""
    updated = EnrichSettingsModel.update(payload.dict())
    return {"code": 0, "data": EnrichSettings(**updated), "message": "success"}


@router.delete("/providers")
def delete_provider(
    name: str,
    current_user: dict = Depends(get_current_user),
):
    """删除一个 provider（按 name，查询参数传递）."""
    ok = ThreatIntelProviderConfig.delete(name)
    if not ok:
        return {"code": 404, "data": None, "message": f"未找到 provider '{name}'"}
    return {"code": 0, "data": None, "message": "success"}
