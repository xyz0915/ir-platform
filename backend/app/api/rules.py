"""规则管理接口."""

import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status

from app.database import get_connection, reset_default_rules
from app.models.rule import Rule, RuleHistory
from app.models.rule_draft import RuleDraft
from app.schemas.analysis import RuleCreate, RuleUpdate, validate_condition
from app.services.auth_service import get_current_user
from app.services.rule_generator import RuleGenerator
from app.services.rule_shadow import RuleShadow
from app.services.rule_tuner import RuleTuner

logger = logging.getLogger(__name__)
router = APIRouter()


def _search_rules(q: str, category: Optional[str], enabled: Optional[bool],
                  current_user: Optional[dict] = None,
                  engine_type: Optional[str] = None) -> list:
    """按关键字搜索规则（T-P2-1）：name/label/description 模糊匹配 + 租户隔离."""
    tenant_id = getattr(current_user, "tenant_id", 0) if current_user else 0
    if not isinstance(tenant_id, int):
        tenant_id = 0
    with get_connection() as conn:
        query = "SELECT * FROM rules WHERE 1=1"
        params: list = []
        # T-P2-1: 多租户隔离钩子
        query += " AND (tenant_id = ? OR tenant_id = 0)"
        params.append(tenant_id)
        like = f"%{q}%"
        query += " AND (name LIKE ? OR label LIKE ? OR description LIKE ?)"
        params.extend([like, like, like])
        if category:
            query += " AND category = ?"
            params.append(category)
        if enabled is not None:
            query += " AND enabled = ?"
            params.append(1 if enabled else 0)
        if engine_type is not None:
            query += " AND engine_type = ?"
            params.append(engine_type)
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
    engine_type: str = Query(None, description="引擎类型: rule_engine / behavior_engine"),
    current_user: dict = Depends(get_current_user),
):
    """获取规则列表（支持类别、启用状态与关键字搜索 + 多租户）."""
    if q:
        rules = _search_rules(q, category, enabled, current_user, engine_type=engine_type)
    else:
        # 非关键字查询也加租户隔离
        tenant_id = getattr(current_user, "tenant_id", 0) if current_user else 0
        if not isinstance(tenant_id, int):
            tenant_id = 0
        rules = Rule.list(category=category, enabled=enabled, tenant_id=tenant_id, engine_type=engine_type)
    return {"code": 0, "data": rules, "message": "success"}


@router.get("/selector")
def list_rules_for_selector(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    category: str = Query(None, description="规则类别"),
    severity: str = Query(None, description="严重度"),
    keyword: str = Query(None, description="关键字搜索"),
    engine_type: str = Query(None, description="引擎类型: rule_engine / behavior_engine"),
    current_user: dict = Depends(get_current_user),
):
    """策略配置中的规则选择器 — 支持分页、类别、严重度、关键字、引擎类型筛选."""
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
            if engine_type:
                conditions.append("engine_type = ?")
                params.append(engine_type)

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
        engine_type=rule.engine_type,
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
    """更新规则（条件结构校验 + 审计写入 + 版本历史 + 分级审批）.

    T-P1-1: 更新时写 rule_history 快照，version 递增。
    若 severity >= 'high' 或 source='default' 则标记 status='pending_approval'，
    需单独审批才生效；普通规则直接生效。
    """
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

    # 判断是否需要审批
    cur_severity = rule.severity or existing.get("severity", "medium")
    cur_source = existing.get("source", "user")
    needs_approval = cur_severity in ("high", "critical") or cur_source == "default"

    result = Rule.update(
        rule_id,
        enabled=rule.enabled,
        condition=rule.condition,
        severity=rule.severity,
        changed_by=current_user.get("username"),
        description=rule.description,
        name=rule.name,
        owner=rule.owner,
        label=rule.label,
        mitre_attack=rule.mitre_attack,
        engine_type=rule.engine_type,
    )
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="规则不存在")

    if needs_approval:
        # 标记为待审批
        with get_connection() as conn:
            conn.execute(
                "UPDATE rules SET status = 'pending_approval' WHERE id = ?",
                (rule_id,),
            )
        result = Rule.get_by_id(rule_id)
        return {"code": 0, "data": result, "message": "高危/基线规则修改已提交审批，等待管理员批准"}

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


# ── T-P1-1: 规则生命周期管理 ─────────────────────────────────


@router.post("/{rule_id}/approve")
def approve_rule(
    rule_id: int,
    current_user: dict = Depends(get_current_user),
):
    """审批规则（仅 admin 角色）."""
    if current_user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="仅管理员可审批规则",
        )
    result = Rule.approve(rule_id, approved_by=current_user.get("username", ""))
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="规则不存在")
    return {"code": 0, "data": result, "message": "规则已审批"}


@router.post("/{rule_id}/revert")
def revert_rule(
    rule_id: int,
    payload: dict,
    current_user: dict = Depends(get_current_user),
):
    """回滚规则到指定版本."""
    target_version = payload.get("version")
    if not target_version:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="必须提供 version 参数",
        )
    try:
        result = Rule.revert(
            rule_id,
            target_version=int(target_version),
            changed_by=current_user.get("username", ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="规则不存在")
    return {"code": 0, "data": result, "message": f"规则已回滚到版本 {target_version}"}


@router.post("/{rule_id}/deprecate")
def deprecate_rule(
    rule_id: int,
    current_user: dict = Depends(get_current_user),
):
    """标记规则为已废弃（deprecated）."""
    result = Rule.deprecate(rule_id, changed_by=current_user.get("username", ""))
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="规则不存在")
    return {"code": 0, "data": result, "message": "规则已标记为废弃"}


@router.get("/{rule_id}/history")
def get_rule_history(
    rule_id: int,
    current_user: dict = Depends(get_current_user),
):
    """获取规则的版本历史（version 降序）."""
    existing = Rule.get_by_id(rule_id)
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="规则不存在")
    history = Rule.list_history(rule_id)
    return {"code": 0, "data": history, "message": "success"}


# ─────────────────────────────────────────────────────────────
# P0-B：规则自生成 + 影子运行 + 自动调优 + 人审启用
# （本文件已通过 main.py 挂载于前缀 /api/rules，故以下路径均为相对路径）
# ─────────────────────────────────────────────────────────────

def _unique_draft_name(base: str) -> str:
    """确保草稿 name 在 rule_drafts 表中唯一（避免 UNIQUE 约束冲突）."""
    import re as _re

    base = _re.sub(r"[^a-zA-Z0-9_]", "_", str(base)).strip("_").lower() or "ai_draft"
    name = base
    suffix = 1
    while RuleDraft.get_by_name(name) is not None:
        name = f"{base}_{suffix}"
        suffix += 1
    return name


def _public_draft(draft: Optional[dict]) -> Optional[dict]:
    """裁剪草稿对外字段（去除内部 JSON 列副本）."""
    if not draft:
        return draft
    draft = dict(draft)
    draft.pop("condition_json", None)
    draft.pop("tuning_history_json", None)
    return draft


@router.post("/generate")
async def generate_rule_draft(
    payload: dict = Body(default={}),
    current_user: dict = Depends(get_current_user),
):
    """基于归一化日志样本，调用 LLM 归纳候选检测规则（降级时启发式生成）."""
    sample_log_ids = payload.get("sample_log_ids") or []
    category = payload.get("category")
    try:
        count = max(1, min(int(payload.get("count", 1) or 1), 5))
    except (TypeError, ValueError):
        count = 1

    logs = RuleShadow.load_sample_logs(ids=sample_log_ids or None)
    if not logs:
        return {"code": -1, "data": None, "message": "暂无归一化日志样本，无法生成规则"}

    generator = RuleGenerator()
    created = []
    for _ in range(count):
        draft = await generator.generate(logs, category=category, user=current_user)
        name = _unique_draft_name(draft.get("name") or "ai_draft")
        obj = RuleDraft.create(
            name=name,
            rule_type=draft.get("rule_type", "list"),
            condition=draft.get("condition") or {},
            category=category or draft.get("category"),
            severity=draft.get("severity", "medium"),
            label=draft.get("label"),
            rationale=draft.get("rationale"),
            expected_fields=draft.get("expected_fields"),
            confidence=draft.get("confidence"),
            source=draft.get("source", "ai"),
            generated_by=current_user.get("user_id"),
            dsl=draft.get("dsl_error"),
        )
        created.append(_public_draft(obj))
    return {"code": 0, "data": {"drafts": created}, "message": "success"}


@router.get("/drafts")
def list_rule_drafts(
    status_filter: str = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
):
    """列出规则草稿（支持按状态筛选 + 分页）."""
    result = RuleDraft.list(status=status_filter, page=page, page_size=page_size)
    result["items"] = [_public_draft(d) for d in result["items"]]
    return {"code": 0, "data": result, "message": "success"}


@router.post("/drafts/{draft_id}/shadow")
def run_draft_shadow(
    draft_id: int,
    current_user: dict = Depends(get_current_user),
):
    """对草稿执行一次影子运行（仅计数，不产生告警）."""
    try:
        stats = RuleShadow.run_shadow(draft_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.error("影子运行失败: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        )
    return {"code": 0, "data": stats, "message": "success"}


@router.get("/drafts/{draft_id}/shadow-stats")
def get_draft_shadow_stats(
    draft_id: int,
    current_user: dict = Depends(get_current_user),
):
    """获取草稿的影子运行统计（命中数 + 样本命中）."""
    draft = RuleDraft.get_by_id(draft_id)
    if not draft:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="草稿不存在")
    return {
        "code": 0,
        "data": {
            "draft_id": draft_id,
            "rule_name": draft.get("name"),
            "status": draft.get("status"),
            "hit_count": draft.get("shadow_hit_count", 0),
            "sample_hits": draft.get("sample_hits") or [],
        },
        "message": "success",
    }


@router.post("/drafts/{draft_id}/tune")
async def tune_rule_draft(
    draft_id: int,
    payload: dict = Body(default={}),
    current_user: dict = Depends(get_current_user),
):
    """基于误报反馈对草稿自动调优，生成新版本草稿（原草稿进入待复审）."""
    draft = RuleDraft.get_by_id(draft_id)
    if not draft:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="草稿不存在")
    false_positive_examples = (payload or {}).get("false_positive_examples") or []
    feedback = (payload or {}).get("feedback")
    tuner = RuleTuner()
    try:
        new_draft = await tuner.tune(
            draft,
            false_positive_examples=false_positive_examples,
            feedback=feedback,
            user=current_user,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("规则调优失败: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        )
    return {"code": 0, "data": _public_draft(new_draft), "message": "success"}


@router.post("/drafts/{draft_id}/enable")
def enable_rule_draft(
    draft_id: int,
    current_user: dict = Depends(get_current_user),
):
    """管理员审批：将草稿升级为正式启用的检测规则（HITL）."""
    if current_user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="仅管理员可审批启用规则草稿",
        )
    draft = RuleDraft.get_by_id(draft_id)
    if not draft:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="草稿不存在")
    if draft.get("status") == RuleDraft.STATUS_REJECTED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="已驳回的草稿不可启用"
        )

    condition = draft.get("condition") or {}
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM rules WHERE name = ?", (draft["name"],)
        ).fetchone()
        if row:
            # 镜像的影子规则升级为正式启用规则
            conn.execute(
                "UPDATE rules SET enabled = 1, is_shadow = 0, "
                "updated_at = datetime('now') WHERE name = ?",
                (draft["name"],),
            )
            rule_id = row["id"]
        else:
            created = Rule.create(
                name=draft["name"],
                category=draft.get("category") or "ai",
                rule_type=draft.get("rule_type"),
                condition=condition,
                severity=draft.get("severity", "medium"),
                description=draft.get("rationale"),
                label=draft.get("label"),
                source="ai",
                changed_by=current_user.get("username"),
            )
            rule_id = created["id"]

    RuleDraft.update(
        draft_id,
        status=RuleDraft.STATUS_ENABLED,
        reviewed_by=current_user.get("user_id"),
    )
    return {"code": 0, "data": {"rule_id": rule_id, "enabled": True}, "message": "success"}


@router.post("/drafts/{draft_id}/reject")
def reject_rule_draft(
    draft_id: int,
    payload: dict = Body(default={}),
    current_user: dict = Depends(get_current_user),
):
    """管理员驳回草稿（HITL）."""
    if current_user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="仅管理员可驳回规则草稿",
        )
    draft = RuleDraft.get_by_id(draft_id)
    if not draft:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="草稿不存在")
    reason = (payload or {}).get("reason")
    RuleDraft.update(
        draft_id,
        status=RuleDraft.STATUS_REJECTED,
        reviewed_by=current_user.get("user_id"),
        reject_reason=reason,
    )
    with get_connection() as conn:
        conn.execute(
            "UPDATE rules SET is_shadow = 0, enabled = 0 WHERE name = ?",
            (draft["name"],),
        )
    return {"code": 0, "data": {"status": "rejected"}, "message": "success"}


# ── T-P2-2b: 规则导出/导入 ─────────────────────────────────


@router.get("/export")
def export_rules(
    tenant_id: int = Query(None, description="租户 ID（可选，不传则全部导出）"),
    current_user: dict = Depends(get_current_user),
):
    """导出规则为 JSON 数组（T-P2-2b）.

    排除 id/created_at/updated_at 字段（导入时自动生成新 ID）。
    导出字段: name, description, category, rule_type, condition, severity,
    enabled, mitre_attack, label, source, owner.
    """
    try:
        with get_connection() as conn:
            sql = (
                "SELECT name, description, category, rule_type, condition, "
                "severity, enabled, mitre_attack, label, source, owner "
                "FROM rules WHERE 1=1"
            )
            params: list = []
            if tenant_id is not None and int(tenant_id) > 0:
                sql += " AND (tenant_id = ? OR tenant_id = 0)"
                params.append(int(tenant_id))
            sql += " ORDER BY category, severity DESC, name"
            rows = conn.execute(sql, params).fetchall()

        rules_export = []
        for row in rows:
            r = dict(row)
            # condition 保留原始 JSON 字符串
            if r.get("condition") and isinstance(r.get("condition"), str):
                try:
                    r["condition"] = json.loads(r["condition"])
                except (json.JSONDecodeError, TypeError):
                    pass
            if "enabled" in r:
                r["enabled"] = bool(r["enabled"])
            rules_export.append(r)

        return {"code": 0, "data": rules_export, "message": "success"}
    except Exception as exc:
        logger.error("规则导出失败: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"导出失败: {exc}",
        )


@router.post("/import")
def import_rules(
    payload: list[dict] = Body(...),
    current_user: dict = Depends(get_current_user),
):
    """导入规则（T-P2-2b）.

    接收 JSON 数组，逐条 INSERT 并创建 rule_history（action='import'）。
    排除 id/created_at/updated_at 字段（自动生成新 ID）。
    返回成功/失败统计。
    """
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="导入数据不能为空",
        )

    success_count = 0
    fail_count = 0
    errors: list[str] = []
    changed_by = current_user.get("username", "import")

    for idx, item in enumerate(payload):
        try:
            name = str(item.get("name", "")).strip()
            if not name:
                fail_count += 1
                errors.append(f"第 {idx+1} 条: name 必填")
                continue

            category = str(item.get("category", "")).strip()
            if not category:
                fail_count += 1
                errors.append(f"第 {idx+1} 条 ({name}): category 必填")
                continue

            rule_type = str(item.get("rule_type", "")).strip()
            if not rule_type:
                fail_count += 1
                errors.append(f"第 {idx+1} 条 ({name}): rule_type 必填")
                continue

            condition = item.get("condition", {})
            if not isinstance(condition, dict):
                condition = {}

            # 校验 condition
            try:
                validate_condition(rule_type, condition)
            except ValueError as ve:
                fail_count += 1
                errors.append(f"第 {idx+1} 条 ({name}): condition 校验失败 - {ve}")
                continue

            severity = str(item.get("severity", "medium")).strip()
            if severity not in ("critical", "high", "medium", "low"):
                severity = "medium"

            enabled = bool(item.get("enabled", True))
            label = str(item.get("label", "")).strip() or None
            source = str(item.get("source", "import")).strip() or "import"
            mitre_attack = str(item.get("mitre_attack", "")).strip() or None
            owner = str(item.get("owner", "")).strip() or None

            with get_connection() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO rules
                        (name, description, category, rule_type, condition,
                         severity, enabled, label, source, mitre_attack, owner)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        name,
                        str(item.get("description", "")).strip() or None,
                        category,
                        rule_type,
                        json.dumps(condition, ensure_ascii=False),
                        severity,
                        1 if enabled else 0,
                        label,
                        source,
                        mitre_attack,
                        owner,
                    ),
                )
                rule_id = cursor.lastrowid

            # 写 rule_history（action='import'）
            if rule_id:
                import_snapshot = json.dumps({
                    "version": 1,
                    "name": name,
                    "condition": json.dumps(condition, ensure_ascii=False),
                    "severity": severity,
                    "category": category,
                    "rule_type": rule_type,
                    "status": "active",
                    "enabled": enabled,
                    "owner": owner,
                    "saved_at": datetime.now().isoformat(),
                }, ensure_ascii=False, default=str)

                try:
                    RuleHistory.create(
                        rule_id=rule_id, version=1,
                        snapshot=import_snapshot, action="import",
                        operator=changed_by,
                    )
                except Exception as exc:
                    logger.warning("写入导入历史失败: %s", exc)

            # 写审计日志（P2-#7）
            try:
                Rule._write_audit(
                    rule_id=rule_id, action="import",
                    changed_by=changed_by,
                    new_val=import_snapshot,
                )
            except Exception as exc:
                logger.warning("写入审计日志失败: %s", exc)

            success_count += 1

        except Exception as exc:
            fail_count += 1
            errors.append(f"第 {idx+1} 条: {exc}")
            logger.warning("规则导入异常: %s", exc)

    return {
        "code": 0 if fail_count == 0 else -1,
        "data": {
            "success": success_count,
            "fail": fail_count,
            "total": len(payload),
            "errors": errors[:20],
        },
        "message": f"导入完成: 成功 {success_count}, 失败 {fail_count}",
    }


# ===================================================================
#  规则统计（P0-#2）
# ===================================================================

@router.get("/stats")
def get_rule_stats(current_user: dict = Depends(get_current_user)):
    tenant_id = getattr(current_user, "tenant_id", 0) if current_user else 0
    if not isinstance(tenant_id, int):
        tenant_id = 0
    tw = " AND (tenant_id = ? OR tenant_id = 0)"
    tp = [tenant_id]
    with get_connection() as conn:
        total = conn.execute(f"SELECT COUNT(*) as c FROM rules WHERE 1=1{tw}", tp).fetchone()["c"]
        enabled = conn.execute(f"SELECT COUNT(*) as c FROM rules WHERE enabled=1{tw}", tp).fetchone()["c"]
        high_risk = conn.execute(f"SELECT COUNT(*) as c FROM rules WHERE severity IN ('critical','high'){tw}", tp).fetchone()["c"]
        medium_risk = conn.execute(f"SELECT COUNT(*) as c FROM rules WHERE severity='medium'{tw}", tp).fetchone()["c"]
        user_rules = conn.execute(f"SELECT COUNT(*) as c FROM rules WHERE source != 'default'{tw}", tp).fetchone()["c"]
        rule_engine_count = conn.execute(f"SELECT COUNT(*) as c FROM rules WHERE engine_type='rule_engine'{tw}", tp).fetchone()["c"]
        behavior_engine_count = conn.execute(f"SELECT COUNT(*) as c FROM rules WHERE engine_type='behavior_engine'{tw}", tp).fetchone()["c"]
    return {"code": 0, "data": {
        "total": total, "enabled": enabled,
        "high_risk": high_risk, "medium_risk": medium_risk,
        "user_rules": user_rules,
        "rule_engine_count": rule_engine_count,
        "behavior_engine_count": behavior_engine_count,
    }}


# ===================================================================
#  规则测试沙盒（P1-#3）
# ===================================================================

@router.post("/test")
def test_rule(
    body: dict = Body(...),
    current_user: dict = Depends(get_current_user),
):
    rule_data = body.get("rule", {})
    sample = body.get("sample", {})
    if not rule_data or not sample:
        raise HTTPException(400, "需要 rule 和 sample 参数")
    rule_type = rule_data.get("rule_type", "regex")
    condition = rule_data.get("condition", {})
    try:
        validate_condition(rule_type, condition)
    except ValueError as e:
        return {"code": -1, "data": {"matched": False, "error": str(e)}}
    from app.rules.rule_engine import RuleEngine
    from app.rules.canonical_adapter import CanonicalAdapter
    item = CanonicalAdapter.to_flat(sample)
    rule_obj = {"id": 0, "name": rule_data.get("name", "test"),
                "rule_type": rule_type, "condition": condition,
                "severity": rule_data.get("severity", "medium"),
                "category": rule_data.get("category", "")}
    try:
        result = RuleEngine.evaluate(item, rule_obj)
        return {"code": 0, "data": {
            "matched": bool(result),
            "confidence": result.get("confidence", 0) if result else 0,
        }}
    except Exception as e:
        return {"code": -1, "data": {"matched": False, "error": str(e)}}