"""检测策略配置 API."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException

from app.models.policy import DetectionPolicy
from app.models.rules import Rule
from app.services.auth_service import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()


# ===== 策略管理 =====

@router.get("/policies")
def list_policies(current_user: dict = Depends(get_current_user)):
    return {"success": True, "data": DetectionPolicy.get_all()}


@router.post("/policies")
def create_policy(
    name: str = Query(...),
    description: str = Query(""),
    enable_rag: int = Query(0),
    enable_attack_chain: int = Query(0),
    tags: str = Query(""),
    current_user: dict = Depends(get_current_user),
):
    pid = DetectionPolicy.create(name, description, enable_rag, enable_attack_chain, tags)
    if pid is None:
        raise HTTPException(500, "创建策略失败")
    return {"success": True, "data": {"id": pid}}


@router.get("/policies/{policy_id}")
def get_policy(policy_id: int, current_user: dict = Depends(get_current_user)):
    policy = DetectionPolicy.get_by_id(policy_id)
    if not policy:
        raise HTTPException(404, "策略不存在")
    return {"success": True, "data": policy}


@router.put("/policies/{policy_id}")
def update_policy(
    policy_id: int,
    name: Optional[str] = Query(None),
    description: Optional[str] = Query(None),
    enable_rag: Optional[int] = Query(None),
    enable_attack_chain: Optional[int] = Query(None),
    tags: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    kwargs = {}
    if name is not None: kwargs["name"] = name
    if description is not None: kwargs["description"] = description
    if enable_rag is not None: kwargs["enable_rag"] = enable_rag
    if enable_attack_chain is not None: kwargs["enable_attack_chain"] = enable_attack_chain
    if tags is not None: kwargs["tags"] = tags
    ok = DetectionPolicy.update(policy_id, **kwargs)
    return {"success": ok}


@router.delete("/policies/{policy_id}")
def delete_policy(policy_id: int, current_user: dict = Depends(get_current_user)):
    ok = DetectionPolicy.delete(policy_id)
    if not ok:
        raise HTTPException(400, "删除失败（激活策略不可删除）")
    return {"success": True}


@router.post("/policies/{policy_id}/activate")
def activate_policy(policy_id: int, current_user: dict = Depends(get_current_user)):
    ok = DetectionPolicy.activate(policy_id)
    return {"success": ok}


@router.post("/policies/{policy_id}/deactivate")
def deactivate_policy(policy_id: int, current_user: dict = Depends(get_current_user)):
    ok = DetectionPolicy.deactivate(policy_id)
    return {"success": ok}


@router.post("/policies/{policy_id}/duplicate")
def duplicate_policy(policy_id: int, current_user: dict = Depends(get_current_user)):
    new_id = DetectionPolicy.duplicate(policy_id)
    if new_id is None:
        raise HTTPException(500, "复制失败")
    return {"success": True, "data": {"id": new_id}}


# ===== 策略规则管理 =====

@router.get("/policies/{policy_id}/rules")
def list_policy_rules(policy_id: int, current_user: dict = Depends(get_current_user)):
    policy = DetectionPolicy.get_by_id(policy_id)
    if not policy:
        raise HTTPException(404, "策略不存在")
    return {"success": True, "data": policy.get("rules", [])}


@router.put("/policies/{policy_id}/rules")
def set_policy_rules(
    policy_id: int,
    rule_ids: list[int] = Query(...),
    current_user: dict = Depends(get_current_user),
):
    ok = DetectionPolicy.set_rules(policy_id, rule_ids)
    return {"success": ok}


# ===== 规则选择器 =====

@router.get("/rules/selector")
def rule_selector(
    category: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    rule_type: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
):
    """规则选择器——多维度筛选."""
    return {"success": True, "data": Rule.search(
        category=category, severity=severity, rule_type=rule_type,
        keyword=keyword, page=page, page_size=page_size,
    )}


# ===== 分析引擎集成 =====

@router.get("/policies/active/info")
def get_active_policy_info(current_user: dict = Depends(get_current_user)):
    """获取当前激活策略（给分析引擎用）. """
    active = DetectionPolicy.get_active()
    return {"success": True, "data": active}
