"""日志检索模块 — Agent JSON 导入与事件归一化服务.

提供导入单条/批量 Agent JSON、查询导入记录、一键生成 SecurityEvent、
以及高级搜索语法解析与 FTS5 全文检索能力.
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
        json.loads(raw_json)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"raw_json 不是合法 JSON: {exc}") from exc

    if collector_type not in COLLECTOR_TYPES:
        raise ValueError(f"不支持的 collector_type: {collector_type}，可选: {COLLECTOR_TYPES}")

    batch_id = batch_id or str(uuid.uuid4())
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO agent_imports
                (import_batch_id, case_id, host_id, collector_type, raw_json, imported_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (batch_id, case_id, host_id, collector_type, raw_json, now),
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
                    json.loads(raw_json)
                except (json.JSONDecodeError, TypeError) as exc:
                    logger.warning("批量导入跳过非法 JSON: %s", exc)
                    continue

                cursor = conn.execute(
                    """
                    INSERT INTO agent_imports
                        (import_batch_id, case_id, host_id, collector_type,
                         collector_name, raw_json, imported_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (batch_id, case_id, host_id, collector_type,
                     collector_name, raw_json, now),
                )
                results.append({
                    "id": cursor.lastrowid,
                    "imported_at": now,
                    "collector_type": collector_type,
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
) -> dict:
    """分页查询导入记录列表.

    Args:
        case_id: 按案件筛选.
        host_id: 按主机筛选.
        collector_type: 按采集器类型筛选.
        start_time: 起始时间（ISO 格式）.
        end_time: 截止时间（ISO 格式）.
        page: 页码（从 1 开始）.
        page_size: 每页条数.

    Returns:
        { total, page, page_size, items }.
    """
    conditions: list[str] = []
    params: list[Any] = []

    if case_id is not None:
        conditions.append("ai.case_id = ?")
        params.append(case_id)
    if host_id is not None:
        conditions.append("ai.host_id = ?")
        params.append(host_id)
    if collector_type:
        conditions.append("ai.collector_type = ?")
        params.append(collector_type)
    if start_time:
        conditions.append("ai.imported_at >= ?")
        params.append(start_time)
    if end_time:
        conditions.append("ai.imported_at <= ?")
        params.append(end_time)

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


def _parse_advanced_query(query_str: str) -> tuple[str, list[Any]]:
    """解析高级搜索语法为 FTS5 查询语句 + 参数列表.

    语法: 条件 ( ("and"|"or") 条件 )*
    条件: 字段 运算符 值
    字段: ip | pid | name | process | severity | startup | ioc | registry | cmdline | user | path | collector
    运算符: "==" | "!=" | "~" | "contains" | "in"
    值: 字符串字面量 (双引号) | 字符串数组

    Args:
        query_str: 高级搜索表达式字符串.

    Returns:
        (fts5_query_string, params_list).

    Raises:
        ValueError: 语法解析失败.
    """
    import re

    SUPPORTED_FIELDS = {
        "ip", "pid", "name", "process", "severity", "startup",
        "ioc", "registry", "cmdline", "user", "path", "collector",
    }

    if not query_str or not query_str.strip():
        return "", []

    # Step 1: 词法分析 - 识别 token
    token_pattern = re.compile(
        r'(ip|pid|name|process|severity|startup|ioc|registry|cmdline|user|path|collector)'
        r'('
        r'==|!=|~|contains|in'
        r')'
        r'"([^"]*)"'
        r'|\(|\)|and\b|or\b',
        re.IGNORECASE,
    )

    tokens: list[str] = []
    pos = 0
    while pos < len(query_str):
        # 跳过空白
        if query_str[pos] in (' ', '\t', '\n'):
            pos += 1
            continue

        match = token_pattern.match(query_str, pos)
        if match:
            tokens.append(match.group(0))
            pos = match.end()
        else:
            # 尝试匹配简单的括号
            if query_str[pos] == '(':
                tokens.append('(')
                pos += 1
            elif query_str[pos] == ')':
                tokens.append(')')
                pos += 1
            elif query_str[pos] == '"':
                # 未识别的引用值
                end = query_str.find('"', pos + 1)
                if end == -1:
                    raise ValueError(f"引号未闭合: position={pos}")
                tokens.append(f'"{query_str[pos+1:end]}"')
                pos = end + 1
            else:
                # 未识别的字符 — 跳过或报错
                pos += 1

    if not tokens:
        return "", []

    # Step 2: 解析为 FTS5 查询片段
    fts5_parts: list[str] = []
    i = 0
    logical_op = None  # None, 'AND', 'OR'

    while i < len(tokens):
        token = tokens[i]

        # 逻辑运算符
        if token.lower() == 'and':
            logical_op = 'AND'
            i += 1
            continue
        elif token.lower() == 'or':
            logical_op = 'OR'
            i += 1
            continue
        elif token in ('(', ')'):
            i += 1
            continue

        # 条件: field op "value"
        field_match = re.match(
            r'(ip|pid|name|process|severity|startup|ioc|registry|cmdline|user|path|collector)'
            r'(==|!=|~|contains|in)'
            r'"([^"]*)"',
            token,
            re.IGNORECASE,
        )
        if not field_match:
            i += 1
            continue

        field = field_match.group(1).lower()
        op = field_match.group(2)
        value = field_match.group(3)

        if op == '==':
            # 精确短语匹配
            fts5_parts.append(f'"{value}"')
        elif op == '!=':
            # 排除匹配
            fts5_parts.append(f'NOT "{value}"')
        elif op == '~':
            # 模糊匹配 — 分词匹配
            fts5_parts.append(value)
        elif op == 'contains':
            # 包含匹配 — 通配
            fts5_parts.append(f'"*{value}*"')
        elif op == 'in':
            # 多值匹配 — 展开为 OR
            # 值格式: (x,y) 或直接在引号中用逗号分隔
            values = [v.strip() for v in value.split(',') if v.strip()]
            sub_parts = [f'"{v}"' for v in values]
            fts5_parts.append(f'({" OR ".join(sub_parts)})')

        i += 1

    if not fts5_parts:
        return "", []

    # 用 AND 或 OR 连接
    join_op = f' {logical_op or "AND"} '
    fts5_query = join_op.join(fts5_parts)

    logger.debug("Parsed advanced query: %s → %s", query_str, fts5_query)
    return fts5_query, []


def search_advanced(
    query_str: str,
    case_id: int | None = None,
    host_id: int | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """执行高级搜索语法查询.

    Args:
        query_str: 高级搜索表达式（如 ip=="1.1.1.1" and severity=="high"）.
        case_id: 按案件筛选.
        host_id: 按主机筛选.
        page: 页码.
        page_size: 每页条数.

    Returns:
        { total, page, page_size, elapsed_ms, parsed_query, items }.
    """
    start_ts = time.time()

    # 解析查询语法
    fts5_query, _ = _parse_advanced_query(query_str)
    if not fts5_query:
        # 空查询返回最近 24h
        return search(keyword="", case_id=case_id, host_id=host_id,
                      page=page, page_size=page_size)

    # 构建 SQL
    conditions: list[str] = []
    params: list[Any] = []

    if case_id is not None:
        conditions.append("ai.case_id = ?")
        params.append(case_id)
    if host_id is not None:
        conditions.append("ai.host_id = ?")
        params.append(host_id)

    where_clause = " AND ".join(conditions) if conditions else "1=1"
    offset = (page - 1) * page_size

    with get_connection() as conn:
        # 总条数
        count_row = conn.execute(
            f"""
            SELECT COUNT(*) as cnt
            FROM agent_imports ai
            JOIN agent_imports_fts fts ON fts.rowid = ai.id
            WHERE agent_imports_fts MATCH ?
              AND {where_clause}
            """,
            [fts5_query, *params],
        ).fetchone()
        total = count_row["cnt"] if count_row else 0

        # 分页数据
        rows = conn.execute(
            f"""
            SELECT ai.*, h.hostname, h.ip_address, c.name as case_name
            FROM agent_imports ai
            JOIN agent_imports_fts fts ON fts.rowid = ai.id
            LEFT JOIN hosts h ON h.id = ai.host_id
            LEFT JOIN cases c ON c.id = ai.case_id
            WHERE agent_imports_fts MATCH ?
              AND {where_clause}
            ORDER BY ai.imported_at DESC
            LIMIT ? OFFSET ?
            """,
            [fts5_query, *params, page_size, offset],
        ).fetchall()

    elapsed_ms = int((time.time() - start_ts) * 1000)
    items = [dict(r) for r in rows]
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "elapsed_ms": elapsed_ms,
        "parsed_query": fts5_query,
        "items": items,
    }


def search(
    keyword: str = "",
    case_id: int | None = None,
    host_id: int | None = None,
    collector_type: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """全文检索 + 结构化筛选.

    Args:
        keyword: 搜索关键字（空值返回最近 24h 全部记录）.
        case_id: 按案件筛选.
        host_id: 按主机筛选.
        collector_type: 按采集器类型筛选.
        start_time: 起始时间.
        end_time: 截止时间.
        page: 页码.
        page_size: 每页条数.

    Returns:
        { total, page, page_size, elapsed_ms, items }.
    """
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
        default_start = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
        conditions.append("ai.imported_at >= ?")
        params.append(start_time or default_start)

    if case_id is not None:
        conditions.append("ai.case_id = ?")
        params.append(case_id)
    if host_id is not None:
        conditions.append("ai.host_id = ?")
        params.append(host_id)
    if collector_type:
        conditions.append("ai.collector_type = ?")
        params.append(collector_type)
    if start_time:
        conditions.append("ai.imported_at >= ?")
        params.append(start_time)
    if end_time:
        conditions.append("ai.imported_at <= ?")
        params.append(end_time)

    where_clause = " AND ".join(conditions) if conditions else "1=1"
    offset = (page - 1) * page_size

    with get_connection() as conn:
        # 总条数
        count_row = conn.execute(
            f"""
            SELECT COUNT(*) as cnt
            FROM agent_imports ai
            {join_fts}
            WHERE {where_clause}
            """,
            params,
        ).fetchone()
        total = count_row["cnt"] if count_row else 0

        # 分页数据
        rows = conn.execute(
            f"""
            SELECT ai.*, h.hostname, h.ip_address, c.name as case_name
            FROM agent_imports ai
            {join_fts}
            LEFT JOIN hosts h ON h.id = ai.host_id
            LEFT JOIN cases c ON c.id = ai.case_id
            WHERE {where_clause}
            ORDER BY ai.imported_at DESC
            LIMIT ? OFFSET ?
            """,
            [*params, page_size, offset],
        ).fetchall()

    elapsed_ms = int((time.time() - start_ts) * 1000)
    items = [dict(r) for r in rows]
    return {"total": total, "page": page, "page_size": page_size, "elapsed_ms": elapsed_ms, "items": items}


def get_trend_data(hours: int = 24) -> list[dict]:
    """获取日志量趋势数据（按小时聚合）.

    Args:
        hours: 回溯小时数，默认 24.

    Returns:
        每小时日志量列表 [{ hour: "2026-07-14 10:00", count: 5 }].
    """
    start = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT strftime('%Y-%m-%d %H:00', imported_at) as hour,
                   COUNT(*) as count
            FROM agent_imports
            WHERE imported_at >= ?
            GROUP BY hour
            ORDER BY hour ASC
            """,
            (start,),
        ).fetchall()
    return [{"hour": r["hour"], "count": r["count"]} for r in rows]
