"""分析中心事件 API 路由 — CRUD + 搜索 + 状态管理 + 批量操作."""

from __future__ import annotations

import csv
import io
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.database import get_connection
from app.models.security_event import (
    STATUS_FLOW,
    SecurityEvent,
    make_event_id,
)
from app.services.auth_service import get_current_user
from app.services.event_filter_service import build_events_where
from app.services.event_normalizer import ingest_events

logger = logging.getLogger(__name__)
router = APIRouter()


# ===================================================================
#  响应辅助
# ===================================================================

def success(data: Any = None) -> dict:
    return {"code": 0, "data": data, "message": "success"}


def error(msg: str, code: int = -1) -> dict:
    return {"code": code, "data": None, "message": msg}


# ===================================================================
#  数据库查询辅助
# ===================================================================

def _row_to_dict(row) -> dict:
    """将 sqlite3.Row 转换为字典（包含 JSON 反序列化）. """
    d = dict(row)
    for field in ("ioc_matches", "evidence", "related_events", "matched_rules"):
        if field in d and isinstance(d[field], str):
            try:
                d[field] = json.loads(d[field])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


def _build_where_clause(
    keyword: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    event_types: str | None = None,
    severities: str | None = None,
    statuses: str | None = None,
    attack_stages: str | None = None,
    assignee: str | None = None,
    attack_chain_id: str | None = None,
) -> tuple[str, list]:
    """构建 WHERE 子句和参数列表."""
    conditions: list[str] = []
    params: list[Any] = []

    if keyword:
        conditions.append("(id LIKE ? OR event_type LIKE ? OR host_id LIKE ?)")
        kw = f"%{keyword}%"
        params.extend([kw, kw, kw])

    if start_time:
        conditions.append("timestamp >= ?")
        params.append(start_time)

    if end_time:
        conditions.append("timestamp <= ?")
        params.append(end_time)

    if event_types:
        types_list = [t.strip() for t in event_types.split(",") if t.strip()]
        if types_list:
            placeholders = ",".join("?" for _ in types_list)
            conditions.append(f"event_type IN ({placeholders})")
            params.extend(types_list)

    if severities:
        sev_list = [s.strip() for s in severities.split(",") if s.strip()]
        if sev_list:
            placeholders = ",".join("?" for _ in sev_list)
            conditions.append(f"severity IN ({placeholders})")
            params.extend(sev_list)

    if statuses:
        stat_list = [s.strip() for s in statuses.split(",") if s.strip()]
        if stat_list:
            placeholders = ",".join("?" for _ in stat_list)
            conditions.append(f"status IN ({placeholders})")
            params.extend(stat_list)

    if attack_stages:
        stage_list = [s.strip() for s in attack_stages.split(",") if s.strip()]
        if stage_list:
            placeholders = ",".join("?" for _ in stage_list)
            conditions.append(f"attack_stage IN ({placeholders})")
            params.extend(stage_list)

    if assignee:
        conditions.append("assignee = ?")
        params.append(assignee)

    if attack_chain_id:
        conditions.append("attack_chain_id = ?")
        params.append(attack_chain_id)

    where = ""
    if conditions:
        where = "WHERE " + " AND ".join(conditions)
    return where, params


# ===================================================================
#  事件列表 + 筛选 + 排序 + 分页
# ===================================================================

@router.get("/events")
def list_events(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    keyword: Optional[str] = Query(None),
    start_time: Optional[str] = Query(None),
    end_time: Optional[str] = Query(None),
    event_types: Optional[str] = Query(None, alias="event_type"),
    severities: Optional[str] = Query(None, alias="severity"),
    statuses: Optional[str] = Query(None, alias="status"),
    attack_stages: Optional[str] = Query(None, alias="attack_stage"),
    assignee: Optional[str] = Query(None),
    attack_chain_id: Optional[str] = Query(None),
    # 新增筛选参数
    case_id: Optional[int] = Query(None),
    host_id: Optional[int] = Query(None),
    filter: str = Query("all"),  # all / matched / unmatched
    rule_id: Optional[int] = Query(None),
    rule_category: Optional[str] = Query(None),
    rule_confidence_min: Optional[float] = Query(None, ge=0.0, le=1.0),
    time_range: Optional[str] = Query(None, regex="^(1h|24h|7d|all)?$"),
    sort_field: str = Query("timestamp"),
    sort_order: str = Query("desc"),
    current_user: dict = Depends(get_current_user),
):
    """事件列表（支持全量筛选 + 排序 + 分页）. """
    valid_sort_fields = {"timestamp", "severity", "event_type", "status", "host_id"}
    # TODO: risk_score 排序需等 enrichment 服务稳定后添加
    # 当前 response 已含 risk_score 字段（在 enrich 后）
    if sort_field not in valid_sort_fields:
        sort_field = "timestamp"
    if sort_order not in ("asc", "desc"):
        sort_order = "desc"

    # 统一使用 event_filter_service 构建 WHERE
    filter_params = {
        "case_id": case_id,
        "host_id": host_id,
        "filter": filter,
        "severity": severities,
        "event_type": event_types,
        "rule_id": rule_id,
        "rule_category": rule_category,
        "rule_confidence_min": rule_confidence_min,
        "time_range": time_range if time_range != "all" else None,
        "keyword": keyword,
        "start_time": start_time,
        "end_time": end_time,
    }
    where, params = build_events_where(filter_params)

    # Attack stage
    if attack_stages:
        stage_list = [s.strip() for s in attack_stages.split(",") if s.strip()]
        if stage_list:
            placeholders = ",".join("?" for _ in stage_list)
            where += f" AND se.attack_stage IN ({placeholders})"
            params.extend(stage_list)

    # Status
    if statuses:
        stat_list = [s.strip() for s in statuses.split(",") if s.strip()]
        if stat_list:
            placeholders = ",".join("?" for _ in stat_list)
            where += f" AND se.status IN ({placeholders})"
            params.extend(stat_list)

    # Assignee
    if assignee:
        where += " AND se.assignee = ?"
        params.append(assignee)

    # Attack chain
    if attack_chain_id:
        where += " AND se.attack_chain_id = ?"
        params.append(attack_chain_id)

    offset = (page - 1) * page_size

    with get_connection() as conn:
        # 总数
        count_sql = f"SELECT COUNT(*) as cnt FROM security_events se {where}"
        total = conn.execute(count_sql, params).fetchone()["cnt"]

        # 数据
        data_sql = f"""
            SELECT se.*, h.hostname, h.ip_address, h.case_id as case_id,
                   c.name as case_name, c.case_number
            FROM security_events se
            LEFT JOIN hosts h ON h.id = se.host_id
            LEFT JOIN cases c ON c.id = h.case_id
            {where}
            ORDER BY se.{sort_field} {sort_order} LIMIT ? OFFSET ?
        """
        data_params = params + [page_size, offset]
        rows = conn.execute(data_sql, data_params).fetchall()

    items = [_row_to_dict(r) for r in rows]

    # 附带统计
    with get_connection() as conn:
        total_all = conn.execute("SELECT COUNT(*) as cnt FROM security_events").fetchone()["cnt"]
        total_matched = conn.execute(
            "SELECT COUNT(*) as cnt FROM security_events WHERE matched_rules IS NOT NULL AND matched_rules != '[]'"
        ).fetchone()["cnt"]
        distinct_rules = conn.execute(
            "SELECT COUNT(DISTINCT json_extract(value, '$.rule_id')) as cnt FROM security_events, json_each(matched_rules)"
        ).fetchone()["cnt"] if total_matched > 0 else 0

    return success({
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items,
        "stats": {
            "total": total_all,
            "matched": total_matched,
            "unmatched": total_all - total_matched,
            "distinct_rules_hit": distinct_rules,
        },
    })


# ===================================================================
#  筛选元数据
# ===================================================================

@router.get("/events/filters")
def get_event_filters(
    case_id: Optional[int] = Query(None),
    host_id: Optional[int] = Query(None),
    filter: str = Query("all"),
    keyword: Optional[str] = Query(None),
    start_time: Optional[str] = Query(None),
    end_time: Optional[str] = Query(None),
    event_types: Optional[str] = Query(None, alias="event_type"),
    severities: Optional[str] = Query(None, alias="severity"),
    rule_id: Optional[int] = Query(None),
    rule_category: Optional[str] = Query(None),
    rule_confidence_min: Optional[float] = Query(None),
    time_range: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """返回筛选面板元数据：案件列表、主机列表、规则命中统计等.
    所有聚合统计（除 cases 列表本身）都应受当前筛选条件约束. """
    # 构建 WHERE 约束（用于除 cases/hit_rule_categories 外的聚合）
    filter_params = {
        "case_id": case_id, "host_id": host_id, "filter": filter,
        "keyword": keyword, "start_time": start_time, "end_time": end_time,
        "event_type": event_types, "severity": severities,
        "rule_id": rule_id, "rule_category": rule_category,
        "rule_confidence_min": rule_confidence_min, "time_range": time_range,
    }
    where, where_params = build_events_where(filter_params)

    with get_connection() as conn:
        # 案件列表（含主机数）— 自身元数据，不受筛选约束
        cases = []
        for r in conn.execute(
            "SELECT c.id, c.name, COUNT(h.id) as host_count "
            "FROM cases c LEFT JOIN hosts h ON h.case_id = c.id "
            "GROUP BY c.id ORDER BY c.name"
        ).fetchall():
            cases.append(dict(r))

        # 主机列表（事件数受筛选约束）
        hosts = []
        for r in conn.execute(
            f"SELECT h.id, h.hostname, h.case_id, "
            f"COALESCE((SELECT COUNT(*) FROM security_events se {where} AND se.host_id = h.id), 0) as event_count "
            f"FROM hosts h ORDER BY h.hostname",
            where_params,
        ).fetchall():
            hosts.append(dict(r))

        # 命中的规则列表（命中数受筛选约束 + json_each 精确匹配 rule_id）
        hit_rules = []
        for r in conn.execute(
            f"SELECT r.id, r.name, r.category, "
            f"COALESCE((SELECT COUNT(DISTINCT se.id) FROM security_events se {where} "
            f"AND EXISTS (SELECT 1 FROM json_each(se.matched_rules) je "
            f"WHERE json_extract(je.value, '$.rule_id') = r.id)), 0) as hit_count "
            f"FROM rules r WHERE r.enabled=1 ORDER BY hit_count DESC",
            where_params,
        ).fetchall():
            if r["hit_count"] > 0:
                hit_rules.append(dict(r))

        # 命中规则分类统计（保留全量，不受筛选约束）
        hit_rule_categories = []
        for r in conn.execute(
            "SELECT r.category, COUNT(DISTINCT r.id) as count "
            "FROM rules r WHERE r.enabled=1 "
            "GROUP BY r.category ORDER BY count DESC"
        ).fetchall():
            hit_rule_categories.append(dict(r))

        # 事件类型分布（受筛选约束）
        event_type_counts = []
        for r in conn.execute(
            f"SELECT event_type as type, COUNT(*) as count "
            f"FROM security_events se {where} GROUP BY event_type ORDER BY count DESC",
            where_params,
        ).fetchall():
            event_type_counts.append(dict(r))

        # 严重度分布（受筛选约束）
        severity_counts = []
        for r in conn.execute(
            f"SELECT severity, COUNT(*) as count "
            f"FROM security_events se {where} GROUP BY severity ORDER BY count DESC",
            where_params,
        ).fetchall():
            severity_counts.append(dict(r))

    return success({
        "cases": cases,
        "hosts": hosts,
        "hit_rules": hit_rules,
        "hit_rule_categories": hit_rule_categories,
        "event_type_counts": event_type_counts,
        "severity_counts": severity_counts,
    })


# ===================================================================
#  统计卡片
# ===================================================================

@router.get("/events/stats")
def event_stats(
    case_id: Optional[int] = Query(None),
    host_id: Optional[int] = Query(None),
    filter: str = Query("all"),
    keyword: Optional[str] = Query(None),
    start_time: Optional[str] = Query(None),
    end_time: Optional[str] = Query(None),
    event_types: Optional[str] = Query(None, alias="event_type"),
    severities: Optional[str] = Query(None, alias="severity"),
    time_range: Optional[str] = Query(None, regex="^(1h|24h|7d|all)?$"),
    current_user: dict = Depends(get_current_user),
):
    """分析中心统计卡片数据（4 个指标: 总事件/已匹配/未匹配/规则数 + 今日新增/今日匹配）. """
    from app.services.event_filter_service import build_events_where

    filter_params = {
        "case_id": case_id,
        "host_id": host_id,
        "filter": filter,
        "severity": severities,
        "event_type": event_types,
        "time_range": time_range if time_range and time_range != "all" else None,
        "keyword": keyword,
        "start_time": start_time,
        "end_time": end_time,
    }
    where, params = build_events_where(filter_params)

    with get_connection() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) as cnt FROM security_events se {where}", params
        ).fetchone()["cnt"]

        # 已匹配
        matched_where = f"{where} AND se.matched_rules IS NOT NULL AND se.matched_rules != '[]'" if where != "WHERE 1=1" else \
            "WHERE se.matched_rules IS NOT NULL AND se.matched_rules != '[]'"
        matched_params = list(params)
        matched_total = conn.execute(
            f"SELECT COUNT(*) as cnt FROM security_events se {matched_where}", matched_params
        ).fetchone()["cnt"]

        # 今日新增
        today_start = "date('now')"
        today_where = f"{where} AND date(se.timestamp) >= {today_start}" if where != "WHERE 1=1" else \
            f"WHERE date(se.timestamp) >= {today_start}"
        today_new = conn.execute(
            f"SELECT COUNT(*) as cnt FROM security_events se {today_where}", params
        ).fetchone()["cnt"]

        # 今日匹配
        today_matched_where = f"{matched_where} AND date(se.timestamp) >= {today_start}"
        today_matched = conn.execute(
            f"SELECT COUNT(*) as cnt FROM security_events se {today_matched_where}", matched_params
        ).fetchone()["cnt"]

        # 命中不同规则数
        distinct_rules = 0
        if matched_total > 0:
            distinct_rules_where = matched_where  # 已含 WHERE 关键字
            row = conn.execute(
                f"SELECT COUNT(DISTINCT json_extract(je.value, '$.rule_id')) as cnt "
                f"FROM security_events se, json_each(se.matched_rules) je "
                f"{distinct_rules_where}",
                matched_params,
            ).fetchone()
            distinct_rules = row["cnt"] if row else 0

    return success({
        "total_events": total,
        "matched_events": matched_total,
        "unmatched_events": total - matched_total,
        "distinct_rules_hit": distinct_rules,
        "today_new": today_new,
        "today_matched": today_matched,
    })


# ===================================================================
#  事件详情
# ===================================================================

@router.get("/events/{event_id}")
def get_event(event_id: str, current_user: dict = Depends(get_current_user)):
    """事件详情."""
    with get_connection() as conn:
        row = conn.execute("""
            SELECT se.*, h.hostname, h.ip_address, h.case_id as case_id,
                   c.name as case_name, c.case_number
            FROM security_events se
            LEFT JOIN hosts h ON h.id = se.host_id
            LEFT JOIN cases c ON c.id = h.case_id
            WHERE se.id = ?
        """, (event_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="事件不存在")
    return success(_row_to_dict(row))


# ===================================================================
#  单条状态变更
# ===================================================================

@router.patch("/events/{event_id}/status")
def update_event_status(
    event_id: str,
    body: dict,
    current_user: dict = Depends(get_current_user),
):
    """单条事件状态变更."""
    new_status = body.get("status", "")
    comment = body.get("comment", "")

    if new_status not in ("pending", "triaging", "investigating", "resolved", "rejected"):
        raise HTTPException(status_code=400, detail="无效的状态值")

    with get_connection() as conn:
        row = conn.execute("SELECT * FROM security_events WHERE id = ?", (event_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="事件不存在")

        old_status = row["status"]
        event = SecurityEvent.from_row(dict(row))
        valid, msg = event.validate_status_transition(new_status)
        if not valid:
            raise HTTPException(status_code=400, detail=msg)

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute(
            "UPDATE security_events SET status = ?, updated_at = ? WHERE id = ?",
            (new_status, now, event_id),
        )
        # 记录状态变更历史
        operator = current_user.get("username", "system")
        conn.execute(
            "INSERT INTO status_history (event_id, old_status, new_status, operator, comment) VALUES (?, ?, ?, ?, ?)",
            (event_id, old_status, new_status, operator, comment),
        )

        updated = dict(conn.execute("SELECT * FROM security_events WHERE id = ?", (event_id,)).fetchone())

    return success({
        "id": updated["id"],
        "status": updated["status"],
        "updated_at": updated["updated_at"],
    })


# ===================================================================
#  批量状态变更
# ===================================================================

@router.patch("/events/batch-status")
def batch_update_status(
    body: dict,
    current_user: dict = Depends(get_current_user),
):
    """批量事件状态变更."""
    event_ids = body.get("event_ids", [])
    new_status = body.get("status", "")
    comment = body.get("comment", "")

    if not event_ids:
        raise HTTPException(status_code=400, detail="event_ids 不能为空")
    if new_status not in ("pending", "triaging", "investigating", "resolved", "rejected"):
        raise HTTPException(status_code=400, detail="无效的状态值")

    placeholders = ",".join("?" for _ in event_ids)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    operator = current_user.get("username", "system")
    updated_count = 0

    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT id, status FROM security_events WHERE id IN ({placeholders})",
            event_ids,
        ).fetchall()

        for row in rows:
            old_status = row["status"]
            allowed = STATUS_FLOW.get(old_status, set())
            if new_status not in allowed:
                continue
            conn.execute(
                "UPDATE security_events SET status = ?, updated_at = ? WHERE id = ?",
                (new_status, now, row["id"]),
            )
            conn.execute(
                "INSERT INTO status_history (event_id, old_status, new_status, operator, comment) VALUES (?, ?, ?, ?, ?)",
                (row["id"], old_status, new_status, operator, comment),
            )
            updated_count += 1

    return success({"updated_count": updated_count})


# ===================================================================
#  指派负责人
# ===================================================================

@router.patch("/events/{event_id}/assign")
def assign_event(
    event_id: str,
    body: dict,
    current_user: dict = Depends(get_current_user),
):
    """指派负责人."""
    assignee = body.get("assignee", "")
    if not assignee:
        raise HTTPException(status_code=400, detail="assignee 不能为空")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM security_events WHERE id = ?", (event_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="事件不存在")
        conn.execute(
            "UPDATE security_events SET assignee = ?, updated_at = ? WHERE id = ?",
            (assignee, now, event_id),
        )
        updated = dict(conn.execute("SELECT * FROM security_events WHERE id = ?", (event_id,)).fetchone())

    return success(updated)


# ===================================================================
#  批量指派
# ===================================================================

@router.patch("/events/batch-assign")
def batch_assign(
    body: dict,
    current_user: dict = Depends(get_current_user),
):
    """批量指派负责人."""
    event_ids = body.get("event_ids", [])
    assignee = body.get("assignee", "")

    if not event_ids:
        raise HTTPException(status_code=400, detail="event_ids 不能为空")
    if not assignee:
        raise HTTPException(status_code=400, detail="assignee 不能为空")

    placeholders = ",".join("?" for _ in event_ids)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    with get_connection() as conn:
        conn.execute(
            f"UPDATE security_events SET assignee = ?, updated_at = ? WHERE id IN ({placeholders})",
            [assignee, now] + event_ids,
        )
        updated_count = conn.execute(
            "SELECT changes() as cnt"
        ).fetchone()["cnt"]

    return success({"updated_count": updated_count})


# ===================================================================
#  攻击链时间轴数据
# ===================================================================

@router.get("/events/timeline")
def timeline_data(
    keyword: Optional[str] = Query(None),
    start_time: Optional[str] = Query(None),
    end_time: Optional[str] = Query(None),
    event_types: Optional[str] = Query(None),
    severities: Optional[str] = Query(None),
    statuses: Optional[str] = Query(None),
    attack_stages: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """攻击链时间轴数据 — 按 attack_chain_id 分组."""
    where, params = _build_where_clause(
        keyword=keyword, start_time=start_time, end_time=end_time,
        event_types=event_types, severities=severities, statuses=statuses,
        attack_stages=attack_stages,
    )

    # 获取有 attack_chain_id 的事件和无 chain 的事件
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT * FROM security_events {where} ORDER BY timestamp ASC",
            params,
        ).fetchall()

    items = [_row_to_dict(r) for r in rows]

    # 按 attack_chain_id 分组
    chains_map: dict[str, dict] = {}
    ungrouped: list[dict] = []

    for ev in items:
        cid = ev.get("attack_chain_id")
        if cid:
            if cid not in chains_map:
                chains_map[cid] = {
                    "chain_id": cid,
                    "stage": ev.get("attack_stage", "unknown"),
                    "events": [],
                }
            chains_map[cid]["events"].append(ev)
        else:
            # 单事件作为独立链
            fake_id = f"single_{ev['id']}"
            chains_map[fake_id] = {
                "chain_id": None,
                "stage": ev.get("attack_stage", "unknown"),
                "events": [ev],
            }

    chains = list(chains_map.values())
    return success({
        "chains": chains,
        "total_groups": len(chains),
        "events": [
            {
                "id": ev.get("id"),
                "timestamp": ev.get("timestamp"),
                "event_type": ev.get("event_type"),
                "severity": ev.get("severity"),
                "host_id": ev.get("host_id"),
            }
            for ev in items
        ],
    })


# ===================================================================
#  关联事件列表
# ===================================================================

@router.get("/events/{event_id}/related")
def get_related_events(event_id: str, current_user: dict = Depends(get_current_user)):
    """获取关联事件列表."""
    with get_connection() as conn:
        row = conn.execute("SELECT related_events FROM security_events WHERE id = ?", (event_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="事件不存在")

    related_ids = json.loads(row["related_events"]) if isinstance(row["related_events"], str) else row["related_events"]
    if not related_ids:
        return success({"events": []})

    placeholders = ",".join("?" for _ in related_ids)
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT * FROM security_events WHERE id IN ({placeholders})",
            related_ids,
        ).fetchall()

    return success({"events": [_row_to_dict(r) for r in rows]})


# ===================================================================
#  状态变更历史
# ===================================================================

@router.get("/events/{event_id}/history")
def get_event_history(event_id: str, current_user: dict = Depends(get_current_user)):
    """事件状态变更历史."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM status_history WHERE event_id = ? ORDER BY created_at DESC",
            (event_id,),
        ).fetchall()

    history = [dict(r) for r in rows]
    return success({"history": history})


# ===================================================================
#  CSV 导出
# ===================================================================

@router.get("/events/export/csv")
def export_csv(
    keyword: Optional[str] = Query(None),
    start_time: Optional[str] = Query(None),
    end_time: Optional[str] = Query(None),
    event_types: Optional[str] = Query(None),
    severities: Optional[str] = Query(None),
    statuses: Optional[str] = Query(None),
    attack_stages: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """导出筛选结果为 CSV."""
    where, params = _build_where_clause(
        keyword=keyword, start_time=start_time, end_time=end_time,
        event_types=event_types, severities=severities, statuses=statuses,
        attack_stages=attack_stages,
    )

    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT * FROM security_events {where} ORDER BY timestamp DESC",
            params,
        ).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "timestamp", "host_id", "event_type", "severity",
                      "source_collector", "attack_chain_id", "attack_stage",
                      "status", "assignee"])
    for r in rows:
        writer.writerow([
            r["id"], r["timestamp"], r["host_id"], r["event_type"], r["severity"],
            r.get("source_collector", ""), r.get("attack_chain_id", ""),
            r.get("attack_stage", ""), r["status"], r.get("assignee", ""),
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=security_events.csv"},
    )


# ===================================================================
#  事件批量写入（Agent/内部使用）
# ===================================================================

@router.post("/events/ingest")
def ingest_events_api(
    body: dict,
    current_user: dict = Depends(get_current_user),
):
    """批量写入归一化事件（Agent/内部使用）."""
    raw_events = body.get("events", [])
    if not raw_events:
        raise HTTPException(status_code=400, detail="events 不能为空")

    result = ingest_events(raw_events)
    return success(result)


# ===================================================================
#  存量规则匹配回填
# ===================================================================

@router.post("/events/batch-match-rules")
def batch_match_rules(
    body: dict,
    current_user: dict = Depends(get_current_user),
):
    """对存量事件批量执行规则匹配回填.

    请求体:
        {"case_id": null, "host_id": null, "limit": 5000}
        case_id/host_id 为 null 表示全部，可指定范围.
        limit 控制每批处理条数，默认 5000.

    响应:
        {"processed": N, "matched": N, "elapsed_ms": N}
    """
    import time as time_module

    from app.services.rule_matcher import match_event

    case_id = body.get("case_id")
    host_id = body.get("host_id")
    batch_limit = body.get("limit", 5000)

    where_conditions: list[str] = ["1=1"]
    sql_params: list = []

    if case_id:
        where_conditions.append("se.host_id IN (SELECT id FROM hosts WHERE case_id=?)")
        sql_params.append(int(case_id))
    if host_id:
        where_conditions.append("se.host_id = ?")
        sql_params.append(int(host_id))

    where = " AND ".join(where_conditions)
    start_ts = time_module.time()
    processed = 0
    matched_total = 0

    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT se.id, se.event_type, se.severity, se.evidence, se.host_id "
            f"FROM security_events se WHERE {where} "
            f"ORDER BY se.timestamp DESC LIMIT ?",
            sql_params + [batch_limit],
        ).fetchall()

        for row in rows:
            try:
                event_dict = {
                    "id": row["id"],
                    "event_type": row["event_type"],
                    "severity": row["severity"],
                    "evidence": json.loads(row["evidence"]) if isinstance(row["evidence"], str) else row["evidence"],
                    "host_id": row["host_id"],
                }
                matched = match_event(event_dict)
                matched_json = json.dumps(matched, ensure_ascii=False)
                conn.execute(
                    "UPDATE security_events SET matched_rules = ? WHERE id = ?",
                    (matched_json, row["id"]),
                )
                if matched:
                    matched_total += 1
                processed += 1
            except Exception as exc:
                logger.warning("回填匹配异常: %s, id=%s", exc, row["id"])
                processed += 1

        conn.commit()

    elapsed_ms = int((time_module.time() - start_ts) * 1000)
    logger.info("存量回填完成: processed=%d, matched=%d, elapsed=%dms", processed, matched_total, elapsed_ms)
    return success({
        "processed": processed,
        "matched": matched_total,
        "elapsed_ms": elapsed_ms,
    })


# ===================================================================
#  事件上下文（T4）
# ===================================================================

@router.get("/events/{event_id}/context")
def get_event_context(
    event_id: str,
    minutes: int = Query(5, description="前后分钟数"),
    current_user: dict = Depends(get_current_user),
):
    """获取事件前后 N 分钟同一主机的事件上下文."""
    from app.services.event_enrichment import get_event_context as get_ctx

    result = get_ctx(event_id, minutes)
    return {"code": 0, "data": result}


@router.get("/events/{event_id}/host-stats")
def get_event_host_stats(
    event_id: str,
    current_user: dict = Depends(get_current_user),
):
    """获取事件所属主机的 24h 统计."""
    from app.database import get_connection
    from app.services.event_enrichment import get_host_stats

    with get_connection() as conn:
        row = conn.execute("SELECT host_id FROM security_events WHERE id=?", (event_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Event not found")
        result = get_host_stats(row["host_id"])
        return {"code": 0, "data": result}


@router.get("/events/{event_id}/impact")
def get_event_impact(
    event_id: str,
    current_user: dict = Depends(get_current_user),
):
    """评估事件影响范围."""
    from app.services.event_enrichment import assess_impact_scope

    result = assess_impact_scope(event_id)
    return {"code": 0, "data": result}
