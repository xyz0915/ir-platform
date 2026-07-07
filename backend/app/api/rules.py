"""规则管理接口."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.models.rule import Rule
from app.schemas.analysis import RuleCreate, RuleUpdate
from app.services.auth_service import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("")
def list_rules(
    category: str = Query(None, description="规则类别"),
    enabled: bool = Query(None, description="启用状态"),
    current_user: dict = Depends(get_current_user),
):
    """获取规则列表."""
    rules = Rule.list(category=category, enabled=enabled)
    return {"code": 0, "data": rules, "message": "success"}


@router.post("")
def create_rule(
    rule: RuleCreate,
    current_user: dict = Depends(get_current_user),
):
    """新增规则."""
    result = Rule.create(
        name=rule.name,
        category=rule.category,
        rule_type=rule.rule_type,
        condition=rule.condition,
        severity=rule.severity,
        description=rule.description,
    )
    return {"code": 0, "data": result, "message": "success"}


@router.put("/{rule_id}")
def update_rule(
    rule_id: int,
    rule: RuleUpdate,
    current_user: dict = Depends(get_current_user),
):
    """更新规则."""
    existing = Rule.get_by_id(rule_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="规则不存在",
        )
    result = Rule.update(
        rule_id,
        enabled=rule.enabled,
        condition=rule.condition,
        severity=rule.severity,
    )
    return {"code": 0, "data": result, "message": "success"}
