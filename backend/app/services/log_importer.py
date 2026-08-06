"""日志检索模块 — Agent JSON 导入与事件归一化服务.

提供导入单条/批量 Agent JSON、查询导入记录、一键生成 SecurityEvent、
以及 FTS5 全文检索能力.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from app.database import get_connection
from app.services.event_normalizer import normalize_batch, bulk_insert

logger = logging.getLogger(__name__)

# ── 采集器类型枚举（与 event_normalizer 一致）──
COLLECTOR_TYPES = [
    "processes", "network", "registry", "files", "persistence",
    "wmi", "behavior", "ioc", "auth", "modules", "pipes",
    "scheduled_tasks", "services", "drivers", "dns", "custom",
]


def import_json(
    host_id: int,
    collector_type: str,
    raw_json: str,
    case_id: int | None = None,
    batch_id: str | None = None,
) -> dict:
    """导入单条 Agent JSON 数据到 agent_imports 表.

    Args:
        host_id: 关联主机 ID.
        collector_type: 采集器类型.
        raw_json: 原始 JSON 字符串.
        case_id: 关联案件 ID（可选）.
        batch_id: 导入批次 ID（可选，自动生成 UUID）.

    Returns:
        { id, imported_at }.

    Raises:
        ValueError: raw_json 不是合法 JSON 或 collector_type 不合法.
    """
    # 校验 JSON 合法性
    try:
        parsed = json.loads(raw_json)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"raw_json 不是合法 JSON: {exc}") from exc

    if collector_type not in COLLECTOR_TYPES:
        raise ValueError(f"不支持的 collector_type: {collector_type}，可选: {COLLECTOR_TYPES}")

    # 计算实际条目数
    if isinstance(parsed, list):
        item_count = len(parsed)
    elif isinstance(parsed, dict):
        item_count = 1
    else:
        item_count = 1

    batch_id = batch_id or str(uuid.uuid4())
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO agent_imports
                (import_batch_id, case_id, host_id, collector_type, raw_json, item_count, imported_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (batch_id, case_id, host_id, collector_type, raw_json, item_count, now),
        )
        import_id = cursor.lastrowid

    logger.info(
        "Agent JSON imported: id=%d, host_id=%d, collector=%s",
        import_id, host_id, collector_type,
    )
    return {"id": import_id, "imported_at": now}


def import_batch(
    host_id: int,
    records: list[dict],
    case_id: int | None = None,
    batch_id: str | None = None,
) -> list[dict]:
    """批量导入 Agent JSON 记录（事务包裹）.

    Args:
        host_id: 关联主机 ID.
        records: 记录列表，每项包含 collector_type, collector_name, raw_json.
        case_id: 关联案件 ID（可选）.
        batch_id: 导入批次 ID（可选）.

    Returns:
        每条导入结果的列表 [{ id, imported_at, collector_type }].
    """
    batch_id = batch_id or str(uuid.uuid4())
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    results: list[dict] = []

    with get_connection() as conn:
        try:
            for record in records:
                collector_type = record.get("collector_type", "custom")
                collector_name = record.get("collector_name", "")
                raw_json = record.get("raw_json", "{}")

                # 校验 JSON
                try:
                    parsed = json.loads(raw_json)
                except (json.JSONDecodeError, TypeError) as exc:
                    logger.warning("批量导入跳过非法 JSON: %s", exc)
                    continue

                # 计算实际条目数
                if isinstance(parsed, list):
                    item_count = len(parsed)
                elif isinstance(parsed, dict):
                    item_count = 1
                else:
                    item_count = 1

                cursor = conn.execute(
                    """
                    INSERT INTO agent_imports
                        (import_batch_id, case_id, host_id, collector_type,
                         collector_name, raw_json, item_count, imported_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (batch_id, case_id, host_id, collector_type,
                     collector_name, raw_json, item_count, now),
                )
                results.append({
                    "id": cursor.lastrowid,
                    "imported_at": now,
                    "collector_type": collector_type,
                    "item_count": item_count,
                })
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    logger.info("Batch import done: %d records for host_id=%d", len(results), host_id)
    return results


def get_import(import_id: int) -> dict | None:
    """获取单条导入详情（含完整 raw_json）.

    Args:
        import_id: 导入记录 ID.

    Returns:
        导入记录字典，或 None（不存在）.
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM agent_imports WHERE id = ?",
            (import_id,),
        ).fetchone()

    if row is None:
        return None
    return dict(row)


def list_imports(
    case_id: int | None = None,
    host_id: int | None = None,
    collector_type: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    page: int = 1,
    page_size: int = 20,
    allowed_host_ids: set[int] | None = None,
) -> dict:
    """分页查询导入记录列表.

    Args:
        case_id: 按案件筛选.
        host_id: 按主机筛选.
        collector_type: 按采集器类型筛选.
        start_time: 起始时间（兼容 T/Z/毫秒格式）.
        end_time: 截止时间（ISO 格式）.
        page: 页码（从 1 开始）.
        page_size: 每页条数.
        allowed_host_ids: ACL 可见主机集合（None=全量；空集合=WHERE 1=0）.

    Returns:
        { total, page, page_size, items }.
    """
    from app.services.time_utils import parse_client_time

    conditions: list[str] = []
    params: list[Any] = []

    if case_id is not None:
        conditions.append("ai.host_id IN (SELECT id FROM hosts WHERE case_id=?)")
        params.append(case_id)
    if host_id is not None:
        conditions.append("ai.host_id = ?")
        params.append(host_id)
    if allowed_host_ids is not None:
        if not allowed_host_ids:
            conditions.append("1=0")  # 空可见集合 → 无结果
        else:
            placeholders = ",".join("?" for _ in allowed_host_ids)
            conditions.append(f"ai.host_id IN ({placeholders})")
            params.extend(sorted(allowed_host_ids))
    if collector_type:
        conditions.append("ai.collector_type = ?")
        params.append(collector_type)
    if start_time:
        conditions.append("ai.imported_at >= ?")
        params.append(parse_client_time(start_time))
    if end_time:
        conditions.append("ai.imported_at <= ?")
        params.append(parse_client_time(end_time))

    where_clause = " AND ".join(conditions) if conditions else "1=1"
    offset = (page - 1) * page_size

    with get_connection() as conn:
        # 总条数
        count_row = conn.execute(
            f"SELECT COUNT(*) as cnt FROM agent_imports ai WHERE {where_clause}",
            params,
        ).fetchone()
        total = count_row["cnt"] if count_row else 0

        # 分页数据
        rows = conn.execute(
            f"""
            SELECT ai.*, h.hostname, h.ip_address, c.name as case_name
            FROM agent_imports ai
            LEFT JOIN hosts h ON h.id = ai.host_id
            LEFT JOIN cases c ON c.id = ai.case_id
            WHERE {where_clause}
            ORDER BY ai.imported_at DESC
            LIMIT ? OFFSET ?
            """,
            [*params, page_size, offset],
        ).fetchall()

    items = [dict(r) for r in rows]
    return {"total": total, "page": page, "page_size": page_size, "items": items}


def to_event(import_id: int) -> dict:
    """将导入记录一键归一化为 SecurityEvent（幂等）.

    流程：
    1. 读取 agent_imports.raw_json
    2. 解析 JSON 为事件列表
    3. 调用 event_normalizer.normalize_batch() 归一化
    4. 调用 bulk_insert() 幂等写入 security_events
    5. 更新 agent_imports.event_id 和 event_created=1

    Args:
        import_id: 导入记录 ID.

    Returns:
        { event_id, inserted }.

    Raises:
        ValueError: 导入记录不存在或 raw_json 解析失败.
    """
    record = get_import(import_id)
    if record is None:
        raise ValueError(f"导入记录不存在: import_id={import_id}")

    if record["event_created"] and record["event_id"]:
        # 幂等：已生成事件，直接返回
        return {"event_id": record["event_id"], "inserted": 0, "already_created": True}

    # 解析 raw_json
    try:
        raw_data = json.loads(record["raw_json"])
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"raw_json 解析失败: {exc}") from exc

    # 统一为列表
    if isinstance(raw_data, dict):
        raw_data = [raw_data]

    # 注入 host_id 和 collector_type
    for item in raw_data:
        if "host_id" not in item:
            item["host_id"] = record["host_id"]
        if "source_collector" not in item:
            item["source_collector"] = record["collector_type"]

    # 归一化
    events = normalize_batch(raw_data)
    if not events:
        raise ValueError("归一化失败：未能从 raw_json 中提取任何有效事件")

    # 规则匹配
    from app.services.event_normalizer import _enrich_with_matched_rules
    _enrich_with_matched_rules(events)

    # 批量写入（幂等去重）
    inserted, skipped = bulk_insert(events)
    event_id = events[0].id

    # 更新 agent_imports 记录
    with get_connection() as conn:
        conn.execute(
            "UPDATE agent_imports SET event_id = ?, event_created = 1 WHERE id = ?",
            (event_id, import_id),
        )

    logger.info(
        "to_event done: import_id=%d → event_id=%s (inserted=%d, skipped=%d)",
        import_id, event_id, inserted, skipped,
    )
    return {"event_id": event_id, "inserted": inserted, "already_created": False}


def search(
    keyword: str = "",
    case_id: int | None = None,
    host_id: int | None = None,
    collector_type: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    page: int = 1,
    page_size: int = 20,
    allowed_host_ids: set[int] | None = None,
) -> dict:
    """全文检索 + 结构化筛选.

    Args:
        keyword: 搜索关键字（空值返回最近 24h 全部记录）.
        case_id: 按案件筛选.
        host_id: 按主机筛选.
        collector_type: 按采集器类型筛选.
        start_time: 起始时间（兼容 T/Z/毫秒格式）.
        end_time: 截止时间.
        page: 页码.
        page_size: 每页条数.
        allowed_host_ids: ACL 可见主机集合（None=全量；空集合=WHERE 1=0）.

    Returns:
        { total, page, page_size, elapsed_ms, items }.
    """
    from app.services.time_utils import parse_client_time

    start_ts = time.time()
    conditions: list[str] = []
    params: list[Any] = []

    if keyword and keyword.strip():
        # FTS5 全文检索
        conditions.append("agent_imports_fts MATCH ?")
        params.append(keyword.strip())
        join_fts = "JOIN agent_imports_fts fts ON fts.rowid = ai.id"
    else:
        join_fts = ""
        # 空 keyword: 默认最近 24h
        default_start = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d %H:%M:%S")
        conditions.append("ai.imported_at >= ?")
        params.append(start_time or default_start)

    if case_id is not None:
        # 修复：ai.case_id 在迁移数据中为 NULL，改用 host.case_id 间接匹配
        conditions.append("ai.host_id IN (SELECT id FROM hosts WHERE case_id=?)")
        params.append(case_id)
    if host_id is not None:
        conditions.append("ai.host_id = ?")
        params.append(host_id)
    if allowed_host_ids is not None:
        if not allowed_host_ids:
            conditions.append("1=0")  # 空可见集合 → 无结果
        else:
            placeholders = ",".join("?" for _ in allowed_host_ids)
            conditions.append(f"ai.host_id IN ({placeholders})")
            params.extend(sorted(allowed_host_ids))
    if collector_type:
        conditions.append("ai.collector_type = ?")
        params.append(collector_type)
    if start_time:
        conditions.append("ai.imported_at >= ?")
        params.append(parse_client_time(start_time))
    if end_time:
        conditions.append("ai.imported_at <= ?")
        params.append(parse_client_time(end_time))

    where_clause = " AND ".join(conditions) if conditions else "1=1"
    offset = (page - 1) * page_size

    with get_connection() as conn:
        # 总条数
        count_row = conn.execute(
            f"SELECT COUNT(*) as cnt FROM agent_imports ai WHERE {where_clause}",
            params,
        ).fetchone()
        total = count_row["cnt"] if count_row else 0

        # 分页数据
        rows = conn.execute(
            f"""
            SELECT ai.*, h.hostname, h.ip_address, c.name as case_name
            FROM agent_imports ai
            LEFT JOIN hosts h ON h.id = ai.host_id
            LEFT JOIN cases c ON c.id = h.case_id
            WHERE {where_clause}
            ORDER BY ai.imported_at DESC
            LIMIT ? OFFSET ?
            """,
            [*params, page_size, offset],
        ).fetchall()

    elapsed_ms = int((time.time() - start_ts) * 1000)
    items = [dict(r) for r in rows]
    return {"total": total, "page": page, "page_size": page_size, "elapsed_ms": elapsed_ms, "items": items}


def get_trend_data(hours: int = 24, allowed_host_ids: set[int] | None = None) -> list[dict]:
    """获取日志量趋势数据（按小时聚合）.

    Args:
        hours: 回溯小时数，默认 24.
        allowed_host_ids: ACL 可见主机集合（None=全量；空集合=返回空）.

    Returns:
        每小时日志量列表 [{ hour: "2026-07-14 10:00", count: 5 }].
    """
    start = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    conditions = ["imported_at >= ?"]
    params: list[Any] = [start]
    if allowed_host_ids is not None:
        if not allowed_host_ids:
            return []
        placeholders = ",".join("?" for _ in allowed_host_ids)
        conditions.append(f"host_id IN ({placeholders})")
        params.extend(sorted(allowed_host_ids))
    where_clause = " AND ".join(conditions)
    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT strftime('%Y-%m-%d %H:00', imported_at) as hour,
                   COUNT(*) as count
            FROM agent_imports
            WHERE {where_clause}
            GROUP BY hour
            ORDER BY hour ASC
            """,
            params,
        ).fetchall()
    return [{"hour": r["hour"], "count": r["count"]} for r in rows]
