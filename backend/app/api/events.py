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
    for field in ("ioc_matches", "evidence", "related_events"):
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
    event_types: Optional[str] = Query(None),
    severities: Optional[str] = Query(None),
    statuses: Optional[str] = Query(None),
    attack_stages: Optional[str] = Query(None),
    assignee: Optional[str] = Query(None),
    attack_chain_id: Optional[str] = Query(None),
    sort_field: str = Query("timestamp"),
    sort_order: str = Query("desc"),
    current_user: dict = Depends(get_current_user),
):
    """事件列表（支持多条件筛选 + 排序 + 分页）."""
    valid_sort_fields = {"timestamp", "severity", "event_type", "status", "host_id"}
    if sort_field not in valid_sort_fields:
        sort_field = "timestamp"
    if sort_order not in ("asc", "desc"):
        sort_order = "desc"

    where, params = _build_where_clause(
        keyword=keyword, start_time=start_time, end_time=end_time,
        event_types=event_types, severities=severities, statuses=statuses,
        attack_stages=attack_stages, assignee=assignee, attack_chain_id=attack_chain_id,
    )

    offset = (page - 1) * page_size

    with get_connection() as conn:
        # 总数
        count_sql = f"SELECT COUNT(*) as cnt FROM security_events {where}"
        total = conn.execute(count_sql, params).fetchone()["cnt"]

        # 数据
        data_sql = f"SELECT * FROM security_events {where} ORDER BY {sort_field} {sort_order} LIMIT ? OFFSET ?"
        data_params = params + [page_size, offset]
        rows = conn.execute(data_sql, data_params).fetchall()

    items = [_row_to_dict(r) for r in rows]
    return success({
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items,
    })


# ===================================================================
#  统计
# ===================================================================

@router.get("/events/stats")
def event_stats(
    keyword: Optional[str] = Query(None),
    start_time: Optional[str] = Query(None),
    end_time: Optional[str] = Query(None),
    event_types: Optional[str] = Query(None),
    severities: Optional[str] = Query(None),
    statuses: Optional[str] = Query(None),
    attack_stages: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """筛选结果统计计数."""
    where, params = _build_where_clause(
        keyword=keyword, start_time=start_time, end_time=end_time,
        event_types=event_types, severities=severities, statuses=statuses,
        attack_stages=attack_stages,
    )

    with get_connection() as conn:
        total = conn.execute(f"SELECT COUNT(*) as cnt FROM security_events {where}", params).fetchone()["cnt"]

        by_severity: dict[str, int] = {}
        for r in conn.execute(f"SELECT severity, COUNT(*) as cnt FROM security_events {where} GROUP BY severity", params).fetchall():
            by_severity[r["severity"]] = r["cnt"]

        by_status: dict[str, int] = {}
        for r in conn.execute(f"SELECT status, COUNT(*) as cnt FROM security_events {where} GROUP BY status", params).fetchall():
            by_status[r["status"]] = r["cnt"]

        by_event_type: dict[str, int] = {}
        for r in conn.execute(f"SELECT event_type, COUNT(*) as cnt FROM security_events {where} GROUP BY event_type", params).fetchall():
            by_event_type[r["event_type"]] = r["cnt"]

    return success({
        "total": total,
        "by_severity": by_severity,
        "by_status": by_status,
        "by_event_type": by_event_type,
    })


# ===================================================================
#  事件详情
# ===================================================================

@router.get("/events/{event_id}")
def get_event(event_id: str, current_user: dict = Depends(get_current_user)):
    """事件详情."""
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM security_events WHERE id = ?", (event_id,)).fetchone()
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
