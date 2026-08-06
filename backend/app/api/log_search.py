"""日志检索 API 路由模块.

提供端点（前缀 /api/log-search）:
  POST   /import                 导入 Agent JSON
  GET    /imports                导入记录列表（分页+筛选）
  GET    /imports/{id}           导入详情
  GET    /search                 全文检索 + 结构化筛选（搜索 security_events）
  GET    /search/advanced        字段 DSL 检索（P0-1）
  GET    /unified-search         统一跨表检索（security_events + agent_imports）
  GET    /search/raw             返回纯文本 JSON
  GET    /search/export          导出搜索结果（JSON/CSV，P0-4 脱敏+审计）
  POST   /imports/{id}/to-event  一键生成 SecurityEvent
  GET    /trend                  日志量趋势数据
  GET    /export-audits          导出审计列表（admin only，P0-4）

【P0-2 ACL】全端点注入可见主机集合；显式资源访问越权 403。
【P0-1 DSL】/search 增 dsl 参数；新增 /search/advanced。
【P0-4 导出】参数补齐 + masked 脱敏开关 + export_audit_log 审计。
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
from app.services.access_control import (
    is_admin,
    resolve_allowed_host_ids,
    require_host_access,
)
from app.services.data_masking import apply as mask_apply
from app.services.data_masking import mask_evidence
from app.models.export_audit_log import ExportAuditLog

logger = logging.getLogger(__name__)

router = APIRouter()


def _success(data: Any = None, message: str = "success") -> dict:
    """统一的成功响应格式."""
    return {"code": 0, "data": data, "message": message}


def _error(message: str = "请求失败", data: Any = None) -> dict:
    """统一的错误响应格式."""
    return {"code": -1, "data": data, "message": message}


def _client_ip(request: Request) -> str:
    """提取客户端 IP（兼容反向代理）。"""
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    if request.client:
        return request.client.host or ""
    return ""


# ── 公共参数构建（/search、/advanced、/export 三处复用，P0-1/P0-4）──


def _build_search_params(
    keyword: str = "",
    dsl: str = "",
    host_id: int | None = None,
    case_id: int | None = None,
    event_type: str | None = None,
    severity: str | None = None,
    attack_stage: str | None = None,
    source_collector: str | None = None,
    status: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """构建 search_events 参数 + field_conditions（DSL 联动）。

    Args:
        dsl: 字段 DSL 表达式（非空时覆盖 keyword，走 field_conditions 下推）。

    Returns:
        {"search_params": {...}, "field_conditions": [...]}。

    Raises:
        HTTPException(400): DSL 解析/安全校验失败。
    """
    search_params: dict[str, Any] = {
        "host_id": host_id,
        "event_type": event_type,
        "severity": severity,
        "attack_stage": attack_stage,
        "source_collector": source_collector,
        "status": status,
        "keyword": keyword if keyword else None,
        "case_id": case_id,
        "date_from": start_time,
        "date_to": end_time,
        "page": page,
        "page_size": page_size,
    }
    field_conditions: list[dict] = []
    if dsl and dsl.strip():
        from app.services.field_dsl import compile_to_conditions, DSLError

        try:
            conds, warnings = compile_to_conditions(dsl)
        except DSLError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        field_conditions = conds
        # DSL 生效时清空 keyword（避免双语义）
        search_params["keyword"] = None
    return {"search_params": search_params, "field_conditions": field_conditions}


# ── 1. POST /import — 导入 Agent JSON ──


@router.post("/import", summary="导入 Agent JSON 数据")
def api_import(body: dict, request: Request, user: dict = Depends(get_current_user)):
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

    # P0-2 ACL：写操作需要目标主机可见且案件角色 >= analyst（owner/analyst）
    try:
        require_host_access(user, int(host_id), min_role="analyst")
    except HTTPException:
        raise

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
    allowed = resolve_allowed_host_ids(user, host_id)
    result = log_importer.list_imports(
        case_id=case_id,
        host_id=host_id,
        collector_type=collector_type,
        start_time=start_time,
        end_time=end_time,
        page=page,
        page_size=page_size,
        allowed_host_ids=allowed,
    )
    return _success(result)


# ── 3. GET /imports/{id} — 导入详情 ──


@router.get("/imports/{import_id}", summary="导入详情（含完整 raw_json）")
def api_get_import(import_id: int, user: dict = Depends(get_current_user)):
    """获取单条导入记录详情."""
    record = log_importer.get_import(import_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"导入记录不存在: id={import_id}")
    # P0-2 ACL：显式资源访问，校验记录 host 归属
    if record.get("host_id") is not None:
        require_host_access(user, int(record["host_id"]))
    return _success(record)


# ── 4. GET /unified-search — 统一跨表检索引擎 ──


def _normalize_import_item(item: dict) -> dict:
    """将 agent_imports 字段映射到 security_events 统一 schema.

    前端 LogResultList 按 security_events 字段渲染，需要做映射。
    """
    return {
        **item,
        "_source": "agent_imports",
        "event_type": item.get("collector_type", ""),
        "timestamp": item.get("imported_at", ""),
        "source_collector": "agent",
        "severity": "info",  # agent_imports 无严重度字段
        "status": "已处理" if item.get("event_created") else "未处理",
        "evidence": item.get("raw_json", "{}"),
    }


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
    allowed = resolve_allowed_host_ids(user, host_id)

    if scope == "events":
        result = search_events(
            host_id=host_id,
            event_type=event_type,
            severity=severity,
            keyword=keyword if keyword else None,
            date_from=start_time, date_to=end_time,
            page=page, page_size=page_size,
            allowed_host_ids=allowed,
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
            allowed_host_ids=allowed,
        )
        for item in result["items"]:
            item["_source"] = "agent_imports"
            # 字段映射：agent_imports → security_events schema
            item["event_type"] = item.get("collector_type", "")
            item["timestamp"] = item.get("imported_at", "")
            item["source_collector"] = "agent"
            item["severity"] = "info"
            item["status"] = "已处理" if item.get("event_created") else "未处理"
            item["evidence"] = item.get("raw_json", "{}")
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
            allowed_host_ids=allowed,
        )
        ai_result = log_importer.search(
            keyword=keyword,
            host_id=host_id,
            start_time=start_time, end_time=end_time,
            page=1, page_size=500,
            allowed_host_ids=allowed,
        )

        # 标记来源并合并
        all_items = []
        for item in se_result.get("items", []):
            item["_source"] = "security_events"
            all_items.append(item)
        for item in ai_result.get("items", []):
            all_items.append(_normalize_import_item(item))

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
    dsl: str = Query("", description="字段 DSL 语法（可选，非空时覆盖 keyword）"),
    host_id: int | None = Query(None, description="主机 ID"),
    case_id: int | None = Query(None, description="案件 ID"),
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
    allowed = resolve_allowed_host_ids(user, host_id)
    built = _build_search_params(
        keyword=keyword, dsl=dsl, host_id=host_id, case_id=case_id,
        event_type=event_type, severity=severity,
        attack_stage=attack_stage, source_collector=source_collector,
        status=status, start_time=start_time, end_time=end_time,
        page=page, page_size=page_size,
    )
    result = search_events(
        **built["search_params"],
        field_conditions=built["field_conditions"],
        allowed_host_ids=allowed,
    )
    elapsed_ms = int((time.time() - start_ts) * 1000)
    result["elapsed_ms"] = elapsed_ms
    if dsl and dsl.strip():
        result["dsl"] = {"parsed": built["field_conditions"], "warnings": []}
    return _success(result)


# ── 5a. GET /search/advanced — 字段 DSL 检索（P0-1）──


@router.get("/search/advanced", summary="字段 DSL 高级检索")
def api_search_advanced(
    dsl: str = Query("", description="字段 DSL 语法（为空等价 /search）"),
    query: str = Query("", description="旧测试契约兼容：非 DSL 时按关键字处理"),
    host_id: int | None = Query(None, description="主机 ID"),
    case_id: int | None = Query(None, description="案件 ID"),
    event_type: str | None = Query(None),
    severity: str | None = Query(None),
    attack_stage: str | None = Query(None),
    source_collector: str | None = Query(None),
    status: str | None = Query(None),
    start_time: str | None = Query(None),
    end_time: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: dict = Depends(get_current_user),
):
    """字段 DSL 检索；dsl 为空 → 等价 /search（兼容旧测试发送 query=... 契约）。"""
    start_ts = time.time()
    allowed = resolve_allowed_host_ids(user, host_id)
    effective_dsl = dsl or ""
    effective_keyword = query or ""
    built = _build_search_params(
        keyword=effective_keyword, dsl=effective_dsl, host_id=host_id, case_id=case_id,
        event_type=event_type, severity=severity,
        attack_stage=attack_stage, source_collector=source_collector,
        status=status, start_time=start_time, end_time=end_time,
        page=page, page_size=page_size,
    )
    result = search_events(
        **built["search_params"],
        field_conditions=built["field_conditions"],
        allowed_host_ids=allowed,
    )
    result["elapsed_ms"] = int((time.time() - start_ts) * 1000)
    result["dsl"] = {"parsed": built["field_conditions"], "warnings": []}
    return _success(result)


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
    # P0-2 ACL：显式资源访问，校验记录 host 归属
    if record.get("host_id") is not None:
        require_host_access(user, int(record["host_id"]))
    try:
        parsed = json.loads(record["raw_json"])
        return _success({"raw_json": parsed})
    except json.JSONDecodeError:
        return _success({"raw_json": record["raw_json"]})


# ── 7. GET /search/export — 导出搜索结果（JSON/CSV，P0-4 脱敏+审计）──


def _mask_item(item: dict) -> dict:
    """对单条 security_events 记录脱敏（含 evidence JSON 递归脱敏）。"""
    masked = mask_apply(dict(item))
    if "evidence" in masked:
        masked["evidence"] = mask_evidence(masked.get("evidence"))
    return masked


@router.get("/search/export", summary="导出搜索结果（JSON/CSV）")
def api_search_export(
    request: Request,
    keyword: str = Query("", description="搜索关键字"),
    dsl: str = Query("", description="字段 DSL 语法"),
    host_id: int | None = Query(None, description="主机 ID"),
    case_id: int | None = Query(None, description="案件 ID"),
    event_type: str | None = Query(None, description="事件类型（逗号分隔）"),
    severity: str | None = Query(None, description="严重度（逗号分隔）"),
    attack_stage: str | None = Query(None, description="攻击阶段"),
    source_collector: str | None = Query(None, description="采集器来源"),
    status: str | None = Query(None, description="事件状态"),
    start_time: str | None = Query(None, description="起始时间"),
    end_time: str | None = Query(None, description="截止时间"),
    format: str = Query("json", regex="^(json|csv)$", description="导出格式"),
    page_size: int = Query(1000, ge=1, le=10000, description="导出条数上限"),
    masked: int = Query(0, ge=0, le=1, description="脱敏开关（viewer 强制脱敏）"),
    user: dict = Depends(get_current_user),
):
    """导出 security_events 搜索结果（参数与 /search 对齐，P0-4）。

    - ACL 注入：越权 host_id → 403；viewer 强制脱敏（masked=1）。
    - 审计：计算 items 后写 export_audit_log（谁/何时/范围/条数/format/masked）。
    """
    # P0-2 ACL：越权 host_id → 403
    allowed = resolve_allowed_host_ids(user, host_id)

    # P0-4 ACL：非 admin 导出 → 默认脱敏（viewer 强制）
    force_masked = 0
    if not is_admin(user):
        force_masked = 1

    built = _build_search_params(
        keyword=keyword, dsl=dsl, host_id=host_id, case_id=case_id,
        event_type=event_type, severity=severity,
        attack_stage=attack_stage, source_collector=source_collector,
        status=status, start_time=start_time, end_time=end_time,
        page=1, page_size=page_size,
    )

    error_msg = ""
    try:
        result = search_events(
            **built["search_params"],
            field_conditions=built["field_conditions"],
            allowed_host_ids=allowed,
        )
        items = result.get("items", [])
        effective_masked = 1 if (masked or force_masked) else 0
        if effective_masked:
            items = [_mask_item(it) for it in items]
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("export search failed")
        items = []
        error_msg = str(exc)

    row_count = len(items)

    # ── 导出审计（无论成败都记录；失败记录 row_count=0 + error）──
    try:
        audit_params = {
            "keyword": keyword, "dsl": dsl, "host_id": host_id, "case_id": case_id,
            "event_type": event_type, "severity": severity,
            "attack_stage": attack_stage, "source_collector": source_collector,
            "status": status, "start_time": start_time, "end_time": end_time,
            "format": format, "page_size": page_size, "masked": effective_masked,
        }
        if error_msg:
            audit_params["error"] = error_msg
        ExportAuditLog.create(
            user_id=user.get("id"),
            username=user.get("username", ""),
            case_id=case_id,
            host_ids=sorted(allowed) if allowed else None,
            query_params=audit_params,
            row_count=row_count,
            format=format,
            masked=effective_masked,
            ip_address=_client_ip(request),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("export audit write failed: %s", exc)

    if error_msg:
        raise HTTPException(status_code=500, detail=f"导出查询失败: {error_msg}")

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


# ── 8. GET /export-audits — 导出审计列表（admin only，P0-4）──


@router.get("/export-audits", summary="导出审计列表（admin only）")
def api_export_audits(
    user_id: int | None = Query(None, description="按用户 ID 过滤"),
    format: str | None = Query(None, description="按导出格式过滤 json/csv"),
    date_from: str | None = Query(None, description="起始时间"),
    date_to: str | None = Query(None, description="截止时间"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: dict = Depends(get_current_user),
):
    """列出导出审计记录（仅 admin）。"""
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="仅管理员可查看导出审计")
    result = ExportAuditLog.list_all(
        user_id=user_id, format=format,
        date_from=date_from, date_to=date_to,
        page=page, page_size=page_size,
    )
    return _success(result)


# ── 9. POST /imports/{id}/to-event — 一键生成事件 ──


@router.post("/imports/{import_id}/to-event", summary="一键生成 SecurityEvent")
def api_to_event(import_id: int, user: dict = Depends(get_current_user)):
    """将导入记录归一化为 SecurityEvent 并写入分析中心."""
    record = log_importer.get_import(import_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"导入记录不存在: id={import_id}")
    # P0-2 ACL：写操作需要目标主机可见且案件角色 >= analyst（owner/analyst）
    if record.get("host_id") is not None:
        require_host_access(user, int(record["host_id"]), min_role="analyst")
    try:
        result = log_importer.to_event(import_id)
        return _success(result)
    except ValueError as exc:
        return _error(str(exc))


# ── 10. GET /trend — 日志量趋势数据 ──


@router.get("/trend", summary="日志量趋势数据（按小时聚合）")
def api_trend(hours: int = 24, user: dict = Depends(get_current_user)):
    """获取近 N 小时的日志量趋势数据."""
    allowed = resolve_allowed_host_ids(user, None)
    data = log_importer.get_trend_data(hours=hours, allowed_host_ids=allowed)
    return _success(data)
