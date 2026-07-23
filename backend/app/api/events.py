"""分析中心事件 API 路由 — CRUD + 搜索 + 状态管理 + 批量操作."""

from __future__ import annotations

import csv
import io
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
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
from app.services.frontend_projection import get_event_display as get_display

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

def _resolve_event_id(conn, event_id: str) -> str | None:
    """将用户传入的 event_id 解析为数据库中真实的 id.

    四级降级策略：
    Level 1 — 精确匹配 security_events.id
    Level 2 — 按 event_key 匹配
    Level 3 — 智能解析 URL slug 格式（6 种正则模式）
    Level 4 — 模糊前缀匹配（LIKE 'cm:xxx:%' ORDER BY id DESC LIMIT 1）
    """
    # ── Level 1: 精确匹配 id ──
    row = conn.execute(
        "SELECT id FROM security_events WHERE id = ?", (event_id,)
    ).fetchone()
    if row:
        return row["id"]

    # ── Level 2: 按 event_key 匹配 ──
    row = conn.execute(
        "SELECT id FROM security_events WHERE event_key = ? LIMIT 1",
        (event_id,),
    ).fetchone()
    if row:
        return row["id"]

    # ── Level 3: 智能解析 URL slug 格式 ──
    import re as _re

    # 按精确→宽泛顺序排列，确保最长/最确定模式优先匹配
    # 每个模式会生成多个候选（处理 prefix 自身是否含 cm 前缀的歧义）
    patterns: list[tuple[str, callable]] = [
        # (1) 标准完整格式: cm:suspicious_startup_items:127
        (r'^cm:([a-z_]+):(\d+)$',
         lambda p, n: [f"cm:{p}:{n}", f"{p}:{n}"]),
        # (2) 缺 cm 后冒号: cmsuspicious_startup_items:127
        (r'^cm([a-z_]+?):(\d+)$',
         lambda p, n: [f"cm:{p}:{n}", f"{p}:{n}"]),
        # (3) 缺数字前冒号: cm:abnormal_processes494
        (r'^cm:([a-z_]+?)(\d+)$',
         lambda p, n: [f"cm:{p}:{n}", f"{p}:{n}"]),
        # (4) 完全无冒号: cmsuspicious_startup_items127
        (r'^cm([a-z_]+?)(\d+)$',
         lambda p, n: [f"cm:{p}:{n}", f"{p}:{n}"]),
        # (5) 缺 cm 前缀但有冒号: suspicious_startup_items:127 或 cmsuspicious_startup_items:143
        (r'^([a-z_]+?):(\d+)$',
         lambda p, n: (
             [f"cm:{p}:{n}"] if not p.startswith("cm")
             else [f"{p}:{n}", f"cm:{p[2:]}:{n}"]  # prefix 含 cm: 去重再加 cm
         )),
        # (6) 缺 cm 前缀且无冒号: suspicious_startup_items127 或 cmsuspicious_startup_items143
        (r'^([a-z_]+?)(\d+)$',
         lambda p, n: (
             [f"cm:{p}:{n}"] if not p.startswith("cm")
             else [f"{p}:{n}", f"cm:{p[2:]}:{n}"]
         )),
    ]

    for regex, build_candidates in patterns:
        m = _re.match(regex, event_id)
        if m:
            candidates = build_candidates(m.group(1), m.group(2))
            for candidate in candidates:
                row = conn.execute(
                    "SELECT id FROM security_events WHERE id = ?", (candidate,)
                ).fetchone()
                if row:
                    return row["id"]

    # ── Level 4: 模糊前缀匹配 ──
    for regex, build_candidates in patterns:
        m = _re.match(regex, event_id)
        if m:
            for candidate in build_candidates(m.group(1), m.group(2)):
                # 取前两段作为前缀: cm:suspicious_startup_items:127 → cm:suspicious_startup_items
                prefix_part = ':'.join(candidate.split(':')[:2])
                row = conn.execute(
                    "SELECT id FROM security_events WHERE id LIKE ? ORDER BY id DESC LIMIT 1",
                    (f"{prefix_part}:%",),
                ).fetchone()
                if row:
                    return row["id"]

    return None


def _lookup_event(conn, event_id: str, join_hosts: bool = True):
    """弹性查询事件：先精确匹配 id，再尝试 event_key，最后尝试模糊前缀匹配.

    当 join_hosts=True 时返回完整 JOIN 查询（含主机/案件信息），
    否则仅返回 security_events 基础行。
    """
    resolved_id = _resolve_event_id(conn, event_id)
    if not resolved_id:
        return None

    if join_hosts:
        return conn.execute("""
            SELECT se.*, h.hostname, h.ip_address, h.case_id as case_id,
                   c.name as case_name, c.case_number
            FROM security_events se
            LEFT JOIN hosts h ON h.id = se.host_id
            LEFT JOIN cases c ON c.id = h.case_id
            WHERE se.id = ?
        """, (resolved_id,)).fetchone()
    else:
        return conn.execute(
            "SELECT * FROM security_events WHERE id = ?", (resolved_id,)
        ).fetchone()


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
    source_collector: Optional[str] = Query(None, alias="source_collector"),
    ai_label: Optional[str] = Query(None, regex="^(recommended|suspicious|false_positive)?$"),
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
        "source_collector": source_collector,
        "ai_label": ai_label,
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

    # 为每行注入 summary / t_code / source（列表渲染用）
    from app.services.event_enrichment import build_event_summary
    from app.services.frontend_projection import infer_t_code, infer_source
    for item in items:
        evi = item.get("evidence")
        if isinstance(evi, str):
            try:
                evi = json.loads(evi)
            except (json.JSONDecodeError, TypeError):
                evi = {}

        # AI 推荐事件：摘要显示原始事件的摘要（evidence._original_summary）
        if item.get("event_type") == "ai_recommended":
            orig_summary = (evi or {}).get("_original_summary", "")
            item["summary"] = orig_summary or "AI推荐事件（原始摘要不可用）"
        else:
            item["summary"] = build_event_summary({
                "event_type": item.get("event_type", ""),
                "severity": item.get("severity", "info"),
                "host_id": item.get("host_id"),
                "hostname": item.get("hostname", ""),
                "evidence": evi,
            })
        # MITRE T-code
        mr = item.get("matched_rules", [])
        if isinstance(mr, str):
            try:
                mr = json.loads(mr)
            except (json.JSONDecodeError, TypeError):
                mr = []
        item["t_code"] = infer_t_code(item.get("event_type", ""), mr if isinstance(mr, list) else [])
        item["source"] = infer_source(item)

    # 附带统计（total_all 不受 filter 约束）
    total_params_raw = dict(filter_params)
    total_params_raw["filter"] = "all"
    total_where_base, total_params_base = build_events_where(total_params_raw)

    with get_connection() as conn:
        total_all = conn.execute(
            f"SELECT COUNT(*) as cnt FROM security_events se {total_where_base}", total_params_base
        ).fetchone()["cnt"]
        # 已匹配规则数（受筛选约束）
        matched_params = list(params)
        matched_where = f"{where} AND se.matched_rules IS NOT NULL AND se.matched_rules != '[]'"
        total_matched = conn.execute(
            f"SELECT COUNT(*) as cnt FROM security_events se {matched_where}",
            matched_params,
        ).fetchone()["cnt"]
        distinct_rules = conn.execute(
            f"SELECT COUNT(DISTINCT json_extract(value, '$.rule_id')) as cnt FROM security_events, json_each(matched_rules) WHERE 1=1"
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
        hits_subq = f"""SELECT json_extract(je.value, '$.rule_id') as rid, COUNT(DISTINCT se.id) as cnt
    FROM security_events se, json_each(se.matched_rules) je
    {where}
    GROUP BY json_extract(je.value, '$.rule_id')"""
        for r in conn.execute(
            f"""SELECT r.id, r.name, r.category, COALESCE(h.cnt, 0) as hit_count
    FROM rules r LEFT JOIN ({hits_subq}) h ON h.rid = r.id
    WHERE r.enabled = 1 AND COALESCE(h.cnt, 0) > 0
    ORDER BY hit_count DESC""",
            where_params,
        ).fetchall():
            hit_rules.append(dict(r))

        # 命中规则分类统计（受筛选约束：当前范围内已命中的规则按 category 聚合）
        hit_rule_categories = []
        # 复用 hit_rules 已计算的子查询结果，避免再扫一次 events
        if hit_rules:
            # 在 Python 层做聚合（hit_rules 已经是按规则去重的小数据集）
            cat_count = {}
            for r in hit_rules:
                cat = r.get("category") or "uncategorized"
                cat_count[cat] = cat_count.get(cat, 0) + 1
            hit_rule_categories = [
                {"category": cat, "count": cnt}
                for cat, cnt in sorted(cat_count.items(), key=lambda x: -x[1])
            ]
        else:
            hit_rule_categories = []

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

    # total_events 不应受 filter(matched/unmatched) 约束——始终返回全部总数
    total_params = dict(filter_params)
    total_params["filter"] = "all"
    total_where, total_params_list = build_events_where(total_params)

    with get_connection() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) as cnt FROM security_events se {total_where}", total_params_list
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

        # AI 推荐/待复核/误报 计数（排除 ai_recommended 事件自身）
        ai_base_where = total_where + " AND se.event_type != 'ai_recommended'"
        ai_base_params = list(total_params_list)

        ai_recommended = conn.execute(
            f"SELECT COUNT(*) as c FROM security_events se {total_where} AND se.event_type='ai_recommended'",
            total_params_list
        ).fetchone()["c"]

        ai_suspicious = conn.execute(
            "SELECT COUNT(*) as c FROM security_events se WHERE json_extract(se.ai_verdict, '$.label')='suspicious'"
        ).fetchone()["c"]

        ai_false_positive = conn.execute(
            "SELECT COUNT(*) as c FROM security_events se WHERE json_extract(se.ai_verdict, '$.label')='false_positive'"
        ).fetchone()["c"]

        # matched_events 排除 AI 推荐事件（避免重复计数）
        matched_total_excluding_ai = matched_total - ai_recommended

    return success({
        "total_events": total,
        "matched_events": matched_total_excluding_ai,
        "unmatched_events": total - matched_total,
        "distinct_rules_hit": distinct_rules,
        "today_new": today_new,
        "today_matched": today_matched,
        "ai_recommended": ai_recommended,
        "ai_suspicious": ai_suspicious,
        "ai_false_positive": ai_false_positive,
    })


# ===================================================================
#  事件详情
# ===================================================================

@router.get("/events/{event_id}")
def get_event(event_id: str, current_user: dict = Depends(get_current_user)):
    """事件详情."""
    with get_connection() as conn:
        row = _lookup_event(conn, event_id)
    if not row:
        raise HTTPException(status_code=404, detail="事件不存在")
    event_dict = _row_to_dict(row)
    # IOC 自动提取
    try:
        from app.services.ioc_extractor import extract_iocs
        evidence_raw = json.loads(event_dict["evidence"]) if isinstance(event_dict.get("evidence"), str) else event_dict.get("evidence", {})
        if evidence_raw:
            event_dict["iocs"] = extract_iocs(evidence_raw)
        else:
            event_dict["iocs"] = {}
    except Exception as exc:
        logger.warning("IOC extraction failed: %s", exc)
        event_dict["iocs"] = {}
    # 同类事件统计
    try:
        event_key = row.get("event_key") if isinstance(row, dict) else row["event_key"]
        if event_key:
            with get_connection() as conn2:
                freq = conn2.execute("""
                    SELECT COUNT(*) as total, MIN(timestamp) as first_seen,
                           MAX(timestamp) as last_seen,
                           COUNT(DISTINCT host_id) as affected_hosts
                    FROM security_events WHERE event_key = ?
                """, (event_key,)).fetchone()
            if freq:
                event_dict["frequency"] = dict(freq)
    except Exception as exc:
        logger.warning("Frequency fetch failed: %s", exc)
    return success(event_dict)


@router.get("/events/{event_id}/display")
def get_event_display(
    event_id: str,
    current_user: dict = Depends(get_current_user),
):
    """事件前端展示投影（v2.1 FrontendProjection）。

    返回必填 14 项 + 辅助 9 项 + 证据双视图（范式化视图 + 完整原始数据），
    供分析中心前端列表/详情直接渲染。详见 analysis_center_optimization_design.md §10。
    """
    result = get_display(event_id)
    if not result:
        # fallback: 事件可能在数据库中但 display 投影未生成
        with get_connection() as conn:
            row = _lookup_event(conn, event_id, join_hosts=False)
        if not row:
            raise HTTPException(status_code=404, detail="事件不存在")
        # 返回基础字段作为降级投影
        d = _row_to_dict(row)
        result = {
            "event": d,
            "projection": {
                "required": {},
                "auxiliary": {},
                "evidence_views": {
                    "normalized": json.loads(d.get("evidence", "{}")) if isinstance(d.get("evidence"), str) else d.get("evidence", {}),
                    "raw": d.get("evidence", {}),
                },
            },
        }
    return success(result)


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
        row = _lookup_event(conn, event_id, join_hosts=False)
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
        row = _lookup_event(conn, event_id, join_hosts=False)
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
        row = _lookup_event(conn, event_id, join_hosts=False)
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
#  进程树
# ===================================================================

@router.get("/events/{event_id}/process-tree")
def get_process_tree(
    event_id: str,
    current_user: dict = Depends(get_current_user),
):
    """获取事件所在主机的进程树."""
    with get_connection() as conn:
        row = _lookup_event(conn, event_id, join_hosts=False)
    if not row:
        raise HTTPException(status_code=404, detail="事件不存在")
    row = dict(row)
    evidence = json.loads(row["evidence"]) if isinstance(row["evidence"], str) else row.get("evidence", {})
    host_id = row["host_id"]
    current_pid = evidence.get("pid")
    current_name = evidence.get("process_name") or evidence.get("name", "?")
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT se.evidence FROM security_events se
            WHERE se.host_id = ? AND se.event_type = 'process_start'
        """, (host_id,)).fetchall()
    proc_map = {}
    for r in rows:
        ev = json.loads(r["evidence"]) if isinstance(r["evidence"], str) else r.get("evidence", {})
        pid = ev.get("pid")
        if pid:
            proc_map[pid] = {"pid": pid, "name": ev.get("process_name") or ev.get("name", "?"),
                             "ppid": ev.get("ppid"), "cmdline": ev.get("command_line") or ev.get("cmdline", "")}
    tree = []
    visited = set()
    pid = current_pid
    depth = 0
    while pid and pid in proc_map and pid not in visited and depth < 10:
        info = proc_map[pid]
        tree.append({"pid": pid, "name": info["name"], "ppid": info["ppid"],
                      "cmdline": info["cmdline"], "depth": depth})
        visited.add(pid)
        pid = info.get("ppid")
        depth += 1
    tree.reverse()
    return success({"tree": tree, "current_pid": current_pid, "current_name": current_name})


# ===================================================================
#  批量操作
# ===================================================================

@router.post("/events/batch-status")
def batch_update_status(
    body: dict = Body(...),
    current_user: dict = Depends(get_current_user),
):
    ids = body.get("ids", [])
    status = body.get("status")
    comment = body.get("comment", "")
    if not ids or not status:
        raise HTTPException(status_code=400, detail="ids 和 status 不能为空")
    with get_connection() as conn:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        ph = ",".join("?" for _ in ids)
        conn.execute(
            f"UPDATE security_events SET status = ?, updated_at = ? WHERE id IN ({ph})",
            [status, now] + ids)
        conn.commit()
    return success({"updated": len(ids)})


@router.post("/events/batch-assign")
def batch_assign(
    body: dict = Body(...),
    current_user: dict = Depends(get_current_user),
):
    ids = body.get("ids", [])
    assignee = body.get("assignee", "")
    if not ids or not assignee:
        raise HTTPException(status_code=400, detail="ids 和 assignee 不能为空")
    with get_connection() as conn:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        ph = ",".join("?" for _ in ids)
        conn.execute(
            f"UPDATE security_events SET assignee = ?, updated_at = ? WHERE id IN ({ph})",
            [assignee, now] + ids)
        conn.commit()
    return success({"updated": len(ids)})


@router.post("/events/batch-link-case")
def batch_link_case(
    body: dict = Body(...),
    current_user: dict = Depends(get_current_user),
):
    ids = body.get("ids", [])
    case_id = body.get("case_id")
    if not ids or not case_id:
        raise HTTPException(status_code=400, detail="ids 和 case_id 不能为空")
    with get_connection() as conn:
        ph = ",".join("?" for _ in ids)
        host_rows = conn.execute(
            f"SELECT DISTINCT host_id FROM security_events WHERE id IN ({ph})", ids).fetchall()
        host_ids = list(set(r["host_id"] for r in host_rows if r["host_id"]))
        hph = ",".join("?" for _ in host_ids)
        if host_ids:
            conn.execute(f"UPDATE hosts SET case_id = ? WHERE id IN ({hph})", [case_id] + host_ids)
        conn.commit()
    return success({"updated": len(host_ids)})


# ===================================================================
#  网络连接图
# ===================================================================

@router.get("/events/{event_id}/network-graph")
def get_network_graph(
    event_id: str,
    current_user: dict = Depends(get_current_user),
):
    """获取事件网络连接关系图数据."""
    with get_connection() as conn:
        row = _lookup_event(conn, event_id, join_hosts=True)
    if not row:
        raise HTTPException(status_code=404, detail="事件不存在")
    rd = dict(row)
    evidence = json.loads(rd["evidence"]) if isinstance(rd["evidence"], str) else rd.get("evidence", {})
    hostname = rd.get("hostname", "") or ("#主机" + str(rd["host_id"]))
    local_ip = rd.get("ip_address") or "?"
    # 兼容两种 evidence 结构：network_connections[] 和单条 flat 结构
    connections = []
    if isinstance(evidence.get("network_connections"), list):
        connections = evidence["network_connections"]
    elif isinstance(evidence.get("connections"), list):
        connections = evidence["connections"]
    elif evidence.get("remote_address") or evidence.get("remote_ip"):
        connections = [evidence]
    nodes, edges, seen_remote = [], [], []
    local_id = "local"
    nodes.append({"id": local_id, "label": hostname, "type": "host", "ip": local_ip})
    for c in connections:
        rip = c.get("remote_address") or c.get("remote_ip") or c.get("dest_ip", "")
        rport = c.get("remote_port") or c.get("dest_port", 0)
        proto = c.get("protocol", "TCP")
        if not rip:
            continue
        if rip not in seen_remote:
            nid = f"r_{rip}"
            nodes.append({"id": nid, "label": rip, "type": "remote", "ip": rip, "port": rport})
            seen_remote.append(rip)
        else:
            nid = f"r_{rip}"
        edges.append({"source": local_id, "target": nid, "protocol": proto, "port": rport, "count": 1})
    em = {}
    for e in edges:
        k = f"{e['source']}→{e['target']}:{e['port']}"
        if k in em: em[k]["count"] += 1
        else: em[k] = e
    return success({"nodes": nodes, "edges": list(em.values()), "local_ip": local_ip})


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
        row = _lookup_event(conn, event_id, join_hosts=False)
        if not row:
            raise HTTPException(404, detail="事件不存在")
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


# ===================================================================
#  根因归因（T-G1 / P1-G）
# ===================================================================

@router.post("/root-cause")
async def root_cause_analysis(
    body: dict,
    current_user: dict = Depends(get_current_user),
):
    """根因归因：传入 {host_id, event_id?}，返回进程树回溯的因果链.

    返回结构（统一经 data_masking 脱敏）：
        {host_id, event_id, root_node, causal_chain, confidence,
         evidence, summary, llm_explanation, process_tree}
    """
    from app.services.agents.root_cause_agent import RootCauseAgent
    from app.services.data_masking import apply as mask_apply

    host_id = body.get("host_id")
    event_id = body.get("event_id")
    if not host_id:
        raise HTTPException(status_code=400, detail="host_id 不能为空")

    agent = RootCauseAgent()
    # RootCauseAgent.analyze(ctx, task) — ctx 携带鉴权用户，task 携带业务参数
    result = await agent.analyze(
        ctx={"user": current_user},
        task={"host_id": host_id, "event_id": event_id},
    )
    # 输出脱敏（符合 §8 的 PII 屏蔽约定）
    result = mask_apply(result)
    return success(result)
