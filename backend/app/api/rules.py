"""规则管理接口."""

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.database import get_connection, reset_default_rules
from app.models.rule import Rule
from app.schemas.analysis import RuleCreate, RuleUpdate, validate_condition
from app.services.auth_service import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()


def _search_rules(q: str, category: Optional[str], enabled: Optional[bool]) -> list:
    """按关键字搜索规则（T-P2-1）：name/label/description 模糊匹配."""
    with get_connection() as conn:
        query = "SELECT * FROM rules WHERE 1=1"
        params: list = []
        like = f"%{q}%"
        query += " AND (name LIKE ? OR label LIKE ? OR description LIKE ?)"
        params.extend([like, like, like])
        if category:
            query += " AND category = ?"
            params.append(category)
        if enabled is not None:
            query += " AND enabled = ?"
            params.append(1 if enabled else 0)
        query += " ORDER BY category, severity DESC, created_at"
        rows = conn.execute(query, params).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            if item.get("condition"):
                try:
                    item["condition"] = json.loads(item["condition"])
                except (json.JSONDecodeError, TypeError):
                    pass
            item["enabled"] = bool(item.get("enabled"))
            results.append(Rule._normalize_mitre(item))
        return results


@router.get("")
def list_rules(
    category: str = Query(None, description="规则类别"),
    enabled: bool = Query(None, description="启用状态"),
    q: str = Query(None, description="关键字搜索（名称/中文名/描述）"),
    current_user: dict = Depends(get_current_user),
):
    """获取规则列表（支持类别、启用状态与关键字搜索）."""
    if q:
        rules = _search_rules(q, category, enabled)
    else:
        rules = Rule.list(category=category, enabled=enabled)
    return {"code": 0, "data": rules, "message": "success"}


@router.get("/selector")
def list_rules_for_selector(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    category: str = Query(None, description="规则类别"),
    severity: str = Query(None, description="严重度"),
    keyword: str = Query(None, description="关键字搜索"),
    current_user: dict = Depends(get_current_user),
):
    """策略配置中的规则选择器 — 支持分页、类别、严重度、关键字筛选."""
    try:
        with get_connection() as conn:
            conditions: list[str] = ["1=1"]
            params: list = []

            if category:
                conditions.append("category = ?")
                params.append(category)
            if severity:
                conditions.append("severity = ?")
                params.append(severity)
            if keyword:
                conditions.append("(name LIKE ? OR label LIKE ? OR description LIKE ?)")
                like = f"%{keyword}%"
                params.extend([like, like, like])

            where = " AND ".join(conditions)

            # 总数
            total = conn.execute(
                f"SELECT COUNT(*) as cnt FROM rules WHERE {where}", params
            ).fetchone()["cnt"]

            # 分页数据
            offset = (page - 1) * page_size
            rows = conn.execute(
                f"SELECT * FROM rules WHERE {where} ORDER BY category, severity DESC, created_at LIMIT ? OFFSET ?",
                [*params, page_size, offset],
            ).fetchall()

            items = []
            for row in rows:
                item = dict(row)
                if item.get("condition"):
                    try:
                        item["condition"] = json.loads(item["condition"])
                    except (json.JSONDecodeError, TypeError):
                        pass
                item["enabled"] = bool(item.get("enabled"))
                items.append(item)

            return {"code": 0, "data": {"items": items, "total": total}}
    except Exception as e:
        logger.error("rules/selector failed: %s", e)
        return {"code": -1, "data": {"items": [], "total": 0}, "message": str(e)}


@router.post("")
def create_rule(
    rule: RuleCreate,
    current_user: dict = Depends(get_current_user),
):
    """新增规则（结构与 behavior pattern 校验，非法返回 422/400）."""
    try:
        validate_condition(rule.rule_type, rule.condition)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    result = Rule.create(
        name=rule.name,
        category=rule.category,
        rule_type=rule.rule_type,
        condition=rule.condition,
        severity=rule.severity,
        description=rule.description,
        label=rule.label,
        source=rule.source,
        changed_by=current_user.get("username"),
    )
    return {"code": 0, "data": result, "message": "success"}


@router.put("/bulk-enable")
def bulk_enable_rules(
    payload: dict,
    current_user: dict = Depends(get_current_user),
):
    """批量启用/禁用规则（T-P2-1）.

    注册在 /{rule_id} 之前，避免被路径参数路由遮蔽。
    Request body: {"ids": [int, ...], "enabled": bool}
    """
    ids = payload.get("ids", [])
    if not isinstance(ids, list) or not ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ids 必须为非空列表",
        )
    enabled = bool(payload.get("enabled", True))
    changed_by = current_user.get("username")
    updated = 0
    for rid in ids:
        if Rule.update(int(rid), enabled=enabled, changed_by=changed_by):
            updated += 1
    return {"code": 0, "data": {"updated": updated}, "message": "success"}


@router.post("/reset")
def reset_default_rules_endpoint(
    current_user: dict = Depends(get_current_user),
):
    """重置默认规则（管理员功能，T-P1-6）.

    仅对 source='default' 的行重新 upsert，保留 source='user' 的用户规则。
    """
    if current_user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="仅管理员可重置默认规则",
        )
    stats = reset_default_rules()
    return {"code": 0, "data": stats, "message": "success"}


@router.put("/{rule_id}")
def update_rule(
    rule_id: int,
    rule: RuleUpdate,
    current_user: dict = Depends(get_current_user),
):
    """更新规则（条件结构校验 + 审计写入）."""
    existing = Rule.get_by_id(rule_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="规则不存在",
        )
    if rule.condition is not None:
        try:
            validate_condition(existing.get("rule_type", ""), rule.condition)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            )
    result = Rule.update(
        rule_id,
        enabled=rule.enabled,
        condition=rule.condition,
        severity=rule.severity,
        changed_by=current_user.get("username"),
    )
    return {"code": 0, "data": result, "message": "success"}


@router.delete("/{rule_id}")
def delete_rule(
    rule_id: int,
    current_user: dict = Depends(get_current_user),
):
    """删除规则（仅 source='user' 可删；默认规则拒绝并返回 403）."""
    try:
        ok = Rule.delete(rule_id, changed_by=current_user.get("username"))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="规则不存在",
        )
    return {"code": 0, "data": None, "message": "success"}


