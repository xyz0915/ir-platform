"""日志检索 API 路由模块.

提供 9 个端点（前缀 /api/log-search）:
  POST   /import                 导入 Agent JSON
  GET    /imports                导入记录列表（分页+筛选）
  GET    /imports/{id}           导入详情
  GET    /search                 全文检索 + 结构化筛选
  GET    /search/advanced        字段运算符高级搜索
  GET    /search/raw             返回纯文本 JSON
  GET    /search/export          导出搜索结果（JSON/CSV）
  POST   /imports/{id}/to-event  一键生成 SecurityEvent
  GET    /trend                  日志量趋势数据

【第①批 T-C1 安全加固】全模块端点已加 ``Depends(get_current_user)`` 鉴权.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.services import log_importer
from app.services.auth_service import get_current_user

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


# ── 4. GET /search — 全文检索 ──


@router.get("/search", summary="全文检索 + 结构化筛选")
def api_search(
    keyword: str = Query("", description="搜索关键字（空值返回最近 24h）"),
    case_id: int | None = Query(None, description="案件 ID"),
    host_id: int | None = Query(None, description="主机 ID"),
    collector_type: str | None = Query(None, description="采集器类型"),
    start_time: str | None = Query(None, description="起始时间"),
    end_time: str | None = Query(None, description="截止时间"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    user: dict = Depends(get_current_user),
):
    """全文检索 agent_imports+ 结构化筛选，支持 FTS5 语法."""
    result = log_importer.search(
        keyword=keyword,
        case_id=case_id,
        host_id=host_id,
        collector_type=collector_type,
        start_time=start_time,
        end_time=end_time,
        page=page,
        page_size=page_size,
    )
    return _success(result)


# ── 5. GET /search/advanced — 高级搜索 ──


@router.get("/search/advanced", summary="字段运算符高级搜索")
def api_search_advanced(
    query: str = Query(..., description="高级搜索表达式"),
    case_id: int | None = Query(None, description="案件 ID"),
    host_id: int | None = Query(None, description="主机 ID"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    user: dict = Depends(get_current_user),
):
    """使用字段运算符语法进行高级搜索.

    语法: ip=="1.1.1.1" and severity=="high"
    支持: ==, !=, ~, contains, in + and/or
    """
    if not query or not query.strip():
        return _error("查询表达式不能为空")

    try:
        result = log_importer.search_advanced(
            query_str=query,
            case_id=case_id,
            host_id=host_id,
            page=page,
            page_size=page_size,
        )
        return _success(result)
    except ValueError as exc:
        return _error(f"语法解析错误: {exc}")


# ── 6. GET /search/raw — 返回纯文本 JSON ──


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


# ── 7. GET /search/export — 导出搜索结果 ──


@router.get("/search/export", summary="导出搜索结果（JSON/CSV）")
def api_search_export(
    keyword: str = Query("", description="搜索关键字"),
    case_id: int | None = Query(None, description="案件 ID"),
    host_id: int | None = Query(None, description="主机 ID"),
    collector_type: str | None = Query(None, description="采集器类型"),
    start_time: str | None = Query(None, description="起始时间"),
    end_time: str | None = Query(None, description="截止时间"),
    format: str = Query("json", regex="^(json|csv)$", description="导出格式"),
    page_size: int = Query(1000, ge=1, le=10000, description="导出条数上限"),
    user: dict = Depends(get_current_user),
):
    """导出搜索结果为 JSON 或 CSV 文件."""
    result = log_importer.search(
        keyword=keyword,
        case_id=case_id,
        host_id=host_id,
        collector_type=collector_type,
        start_time=start_time,
        end_time=end_time,
        page=1,
        page_size=page_size,
    )
    items = result.get("items", [])

    if format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        # 写入表头
        headers = [
            "id", "import_batch_id", "case_id", "host_id", "hostname",
            "ip_address", "case_name", "collector_type", "collector_name",
            "item_count", "imported_at", "event_id", "event_created",
        ]
        writer.writerow(headers)
        for item in items:
            writer.writerow([item.get(h, "") for h in headers])
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=log_search_export.csv"},
        )
    else:
        # JSON 格式
        return StreamingResponse(
            iter([json.dumps(items, ensure_ascii=False, indent=2)]),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=log_search_export.json"},
        )


# ── 8. POST /imports/{id}/to-event — 一键生成事件 ──


@router.post("/imports/{import_id}/to-event", summary="一键生成 SecurityEvent")
def api_to_event(import_id: int, user: dict = Depends(get_current_user)):
    """将导入记录归一化为 SecurityEvent 并写入分析中心."""
    try:
        result = log_importer.to_event(import_id)
        return _success(result)
    except ValueError as exc:
        return _error(str(exc))


# ── 9. GET /trend — 日志量趋势数据 ──


@router.get("/trend", summary="日志量趋势数据（按小时聚合）")
def api_trend(hours: int = 24, user: dict = Depends(get_current_user)):
    """获取近 N 小时的日志量趋势数据."""
    data = log_importer.get_trend_data(hours=hours)
    return _success(data)
