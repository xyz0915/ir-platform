"""日志检索 API 路由模块.

提供 9 个端点（前缀 /api/log-search）:
  POST   /import                 导入 Agent JSON
  GET    /imports                导入记录列表（分页+筛选）
  GET    /imports/{id}           导入详情
  GET    /search                 全文检索 + 结构化筛选（搜索 security_events）
  GET    /unified-search         统一跨表检索（security_events + agent_imports）
  GET    /search/raw             返回纯文本 JSON
  GET    /search/export          导出搜索结果（JSON/CSV）
  POST   /imports/{id}/to-event  一键生成 SecurityEvent
  GET    /trend                  日志量趋势数据

【第①批 T-C1 安全加固】全模块端点已加 ``Depends(get_current_user)`` 鉴权.
【P0-1 改造】/search 和 /search/export 已从 agent_imports FTS5 改为 security_events 表.
【P2 新增】/unified-search 统一跨表检索（security_events + agent_imports）.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.services import log_importer
from app.services.auth_service import get_current_user
from app.services.nl_log_search import search_events

logger = logging.getLogger(__name__)

router = APIRouter()


def _success(data: Any = None, message: str = "success") -> dict:
    """统一的成功响应格式."""
    return {"code": 0, "data": data, "message": message}


def _error(message: str = "请求失败", data: Any = None) -> dict:
    """统一的错误响应格式."""
    return {"code": -1, "data": data, "message": message}


# ── 1. POST /import — 导入 Agent JSON ──


@router.post("/import", summary="导入 Agent JSON 数据")
def api_import(body: dict, user: dict = Depends(get_current_user)):
    """导入单条 Agent JSON 数据.

    Body:
        {
            "host_id": 1,
            "collector_type": "network",
            "collector_name": "osquery_network",
            "raw_json": "{...}",
            "case_id": 1          # 可选
        }
    """
    host_id = body.get("host_id")
    collector_type = body.get("collector_type", "custom")
    collector_name = body.get("collector_name", "")
    raw_json = body.get("raw_json", "")
    case_id = body.get("case_id")

    if not host_id:
        return _error("缺少必填字段: host_id")
    if not raw_json:
        return _error("缺少必填字段: raw_json")

    try:
        result = log_importer.import_json(
            host_id=host_id,
            collector_type=collector_type,
            raw_json=raw_json,
            case_id=case_id,
        )
        return _success(result)
    except ValueError as exc:
        return _error(str(exc))


# ── 2. GET /imports — 导入记录列表 ──


@router.get("/imports", summary="导入记录列表（分页+筛选）")
def api_list_imports(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    case_id: int | None = Query(None, description="案件 ID"),
    host_id: int | None = Query(None, description="主机 ID"),
    collector_type: str | None = Query(None, description="采集器类型"),
    start_time: str | None = Query(None, description="起始时间"),
    end_time: str | None = Query(None, description="截止时间"),
    user: dict = Depends(get_current_user),
):
    """获取导入记录的分页列表，支持多维筛选."""
    result = log_importer.list_imports(
        case_id=case_id,
        host_id=host_id,
        collector_type=collector_type,
        start_time=start_time,
        end_time=end_time,
        page=page,
        page_size=page_size,
    )
    return _success(result)


# ── 3. GET /imports/{id} — 导入详情 ──


@router.get("/imports/{import_id}", summary="导入详情（含完整 raw_json）")
def api_get_import(import_id: int, user: dict = Depends(get_current_user)):
    """获取单条导入记录详情."""
    record = log_importer.get_import(import_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"导入记录不存在: id={import_id}")
    return _success(record)


# ── 4. GET /unified-search — 统一跨表检索引擎 ──


@router.get("/unified-search", summary="统一跨表检索（security_events + agent_imports）")
def api_unified_search(
    keyword: str = Query("", description="搜索关键字"),
    scope: str = Query("events", regex="^(events|imports|all)$", description="搜索范围: events/imports/all"),
    host_id: int | None = Query(None),
    event_type: str | None = Query(None),
    severity: str | None = Query(None),
    start_time: str | None = Query(None, alias="start_time"),
    end_time: str | None = Query(None, alias="end_time"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: dict = Depends(get_current_user),
):
    """统一跨表检索。

    scope=events: 只搜 security_events（默认）
    scope=imports: 只搜 agent_imports（FTS5）
    scope=all: 搜两张表，合并按时间排序
    """
    start_ts = time.time()

    if scope == "events":
        result = search_events(
            host_id=host_id,
            event_type=event_type,
            severity=severity,
            keyword=keyword if keyword else None,
            date_from=start_time, date_to=end_time,
            page=page, page_size=page_size,
        )
        # 标记来源
        for item in result["items"]:
            item["_source"] = "security_events"
        result["elapsed_ms"] = int((time.time() - start_ts) * 1000)
        return _success(result)

    elif scope == "imports":
        result = log_importer.search(
            keyword=keyword,
            host_id=host_id,
            start_time=start_time, end_time=end_time,
            page=page, page_size=page_size,
        )
        for item in result["items"]:
            item["_source"] = "agent_imports"
        result["elapsed_ms"] = result.get("elapsed_ms", int((time.time() - start_ts) * 1000))
        return _success(result)

    else:  # scope == "all"
        # 从两张表各取最多 500 条，合并排序
        se_result = search_events(
            host_id=host_id,
            event_type=event_type, severity=severity,
            keyword=keyword if keyword else None,
            date_from=start_time, date_to=end_time,
            page=1, page_size=500,
        )
        ai_result = log_importer.search(
            keyword=keyword,
            host_id=host_id,
            start_time=start_time, end_time=end_time,
            page=1, page_size=500,
        )

        # 标记来源并合并
        all_items = []
        for item in se_result.get("items", []):
            item["_source"] = "security_events"
            all_items.append(item)
        for item in ai_result.get("items", []):
            item["_source"] = "agent_imports"
            all_items.append(item)

        # 按 timestamp 降序排序
        all_items.sort(key=lambda x: x.get("timestamp", "") or x.get("imported_at", "") or "", reverse=True)

        total = len(all_items)
        start = (page - 1) * page_size
        paged = all_items[start:start + page_size]

        return _success({
            "total": total,
            "page": page,
            "page_size": page_size,
            "elapsed_ms": int((time.time() - start_ts) * 1000),
            "items": paged,
        })


# ── 5. GET /search — 全文检索（搜索 security_events 表）──


@router.get("/search", summary="全文检索 + 结构化筛选（搜索 security_events）")
def api_search(
    keyword: str = Query("", description="搜索关键字（空值返回所有，按时间倒序）"),
    host_id: int | None = Query(None, description="主机 ID"),
    event_type: str | None = Query(None, description="事件类型（逗号分隔）"),
    severity: str | None = Query(None, description="严重度（逗号分隔）"),
    attack_stage: str | None = Query(None, description="攻击阶段"),
    source_collector: str | None = Query(None, description="采集器来源"),
    status: str | None = Query(None, description="事件状态"),
    start_time: str | None = Query(None, alias="start_time", description="起始时间"),
    end_time: str | None = Query(None, alias="end_time", description="截止时间"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    user: dict = Depends(get_current_user),
):
    """搜索安全事件（security_events 表），替代原先的 agent_imports FTS5 搜索。"""
    start_ts = time.time()
    result = search_events(
        host_id=host_id,
        event_type=event_type,
        severity=severity,
        attack_stage=attack_stage,
        source_collector=source_collector,
        status=status,
        keyword=keyword if keyword else None,
        date_from=start_time,
        date_to=end_time,
        page=page,
        page_size=page_size,
    )
    elapsed_ms = int((time.time() - start_ts) * 1000)
    result["elapsed_ms"] = elapsed_ms
    return _success(result)


# ── 5. GET /search/raw — 返回纯文本 JSON ──


@router.get("/search/raw", summary="返回纯文本 JSON")
def api_search_raw(
    id: int = Query(..., description="导入记录 ID"),
    user: dict = Depends(get_current_user),
):
    """返回指定导入记录的原始 JSON 内容（纯文本）. """
    record = log_importer.get_import(id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"导入记录不存在: id={id}")
    try:
        parsed = json.loads(record["raw_json"])
        return _success({"raw_json": parsed})
    except json.JSONDecodeError:
        return _success({"raw_json": record["raw_json"]})


# ── 6. GET /search/export — 导出搜索结果（搜索 security_events）──


@router.get("/search/export", summary="导出搜索结果（JSON/CSV）")
def api_search_export(
    keyword: str = Query("", description="搜索关键字"),
    host_id: int | None = Query(None, description="主机 ID"),
    event_type: str | None = Query(None, description="事件类型（逗号分隔）"),
    severity: str | None = Query(None, description="严重度（逗号分隔）"),
    start_time: str | None = Query(None, description="起始时间"),
    end_time: str | None = Query(None, description="截止时间"),
    format: str = Query("json", regex="^(json|csv)$", description="导出格式"),
    page_size: int = Query(1000, ge=1, le=10000, description="导出条数上限"),
    user: dict = Depends(get_current_user),
):
    """导出 security_events 搜索结果（替代原先的 agent_imports FTS5 导出）。"""
    result = search_events(
        host_id=host_id,
        event_type=event_type,
        severity=severity,
        keyword=keyword if keyword else None,
        date_from=start_time,
        date_to=end_time,
        page=1,
        page_size=page_size,
    )
    items = result.get("items", [])

    if format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        # security_events 表头
        headers = [
            "id", "host_id", "hostname", "event_type", "severity",
            "attack_stage", "source_collector", "status", "timestamp",
            "summary", "matched_rules", "evidence",
        ]
        writer.writerow(headers)
        for item in items:
            writer.writerow([item.get(h, "") for h in headers])
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=security_events_export.csv"},
        )
    else:
        # JSON 格式
        return StreamingResponse(
            iter([json.dumps(items, ensure_ascii=False, indent=2)]),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=security_events_export.json"},
        )


# ── 7. POST /imports/{id}/to-event — 一键生成事件 ──


@router.post("/imports/{import_id}/to-event", summary="一键生成 SecurityEvent")
def api_to_event(import_id: int, user: dict = Depends(get_current_user)):
    """将导入记录归一化为 SecurityEvent 并写入分析中心."""
    try:
        result = log_importer.to_event(import_id)
        return _success(result)
    except ValueError as exc:
        return _error(str(exc))


# ── 8. GET /trend — 日志量趋势数据 ──


@router.get("/trend", summary="日志量趋势数据（按小时聚合）")
def api_trend(hours: int = 24, user: dict = Depends(get_current_user)):
    """获取近 N 小时的日志量趋势数据."""
    data = log_importer.get_trend_data(hours=hours)
    return _success(data)
