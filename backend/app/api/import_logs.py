"""手工日志导入 API — 上传、预览、记录查询、任务状态轮询."""

import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status

from app.models.host import Host
from app.models.import_record import ImportRecord
from app.models.import_result import ImportResult
from app.services.auth_service import get_current_user
from app.services.import_log_service import ImportLogService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/hosts/{host_id}/import-logs", tags=["手工日志导入"])


def _get_host_or_404(host_id: int) -> dict:
    """获取主机，不存在则抛 404."""
    host = Host.get_by_id(host_id)
    if not host:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"主机 {host_id} 不存在",
        )
    return host


def _parse_preview(file_path: str, log_type: str, filename: str) -> dict:
    """解析文件的前 10 条记录用于预览.

    Args:
        file_path: 磁盘上的临时文件路径.
        log_type: 日志类型（如 'evtx', 'nginx_access'）.
        filename: 原始文件名（用于格式检测）.

    Returns:
        dict: {detected_format, raw_fields(list), translated(list), stats{total, high, medium, info, low}}.
    """
    from app.parsers.format_detector import FormatDetector, UnsupportedFormatError
    from app.parsers.evtx_parser import EvtxParser
    from app.parsers.access_log_parser import AccessLogParser
    from app.parsers.translator import Translator

    max_lines = 10
    host_id = 0
    hostname = "preview"

    # 检测格式
    if not log_type or log_type == "auto":
        with open(file_path, "rb") as f:
            header = f.read(16)
        first_lines: list[str] = []
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                for i, line in enumerate(f):
                    if i >= 5:
                        break
                    first_lines.append(line)
        except Exception:
            pass
        log_source, detected_format = FormatDetector.detect(
            filename, header, first_lines,
        )
    else:
        log_source = log_type
        detected_format = log_type

    # 解析前 max_lines 条
    parsed_items: list[dict] = []
    if log_source == "evtx":
        # EVTX 解析全部，只取前 N 条用于预览
        try:
            all_items = EvtxParser.parse(file_path, host_id, hostname)
            parsed_items = all_items[:max_lines]
        except Exception:
            parsed_items = []
    else:
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                lines = [line for line in f.readlines() if line.strip()]
            first_items = AccessLogParser.parse(lines[:50], log_source, host_id, hostname)
            parsed_items = first_items[:max_lines]
        except Exception:
            parsed_items = []

    # 翻译
    translated = Translator.translate(parsed_items, host_id)

    # 统计
    total_count = len(parsed_items)
    stats = {"total": total_count, "high": 0, "medium": 0, "info": 0, "low": 0}
    for t in translated:
        sev = t.get("severity", "info")
        if sev in stats:
            stats[sev] += 1

    # 构造预览原始字段（不包含文件路径等敏感信息）
    raw_fields = []
    for item in parsed_items:
        safe_item = {k: v for k, v in item.items()
                     if k not in ("file_path", "host_id", "hostname")}
        raw_fields.append(safe_item)

    return {
        "detected_format": detected_format,
        "log_source": log_source,
        "raw_fields": raw_fields,
        "translated": translated,
        "stats": stats,
    }


@router.post("/preview")
async def preview_import_logs(
    host_id: int,
    file: UploadFile = File(...),
    log_type: str = Form("auto"),
    current_user: dict = Depends(get_current_user),
):
    """预览日志解析结果（前 10 条，不入库）.

    Args:
        host_id: 主机 ID.
        file: 上传的日志文件.
        log_type: 日志类型（auto/evtx/nginx_access 等）.
    """
    _get_host_or_404(host_id)

    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="文件名不能为空",
        )

    # 保存到临时路径
    suffix = Path(file.filename).suffix or ".tmp"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        preview_data = _parse_preview(tmp_path, log_type, file.filename)

        return {
            "code": 0,
            "data": {
                "file_name": file.filename,
                "detected_format": preview_data["detected_format"],
                "log_source": preview_data["log_source"],
                "raw_fields": preview_data["raw_fields"],
                "translated": preview_data["translated"],
                "stats": preview_data["stats"],
            },
            "message": "success",
        }
    except Exception as e:
        logger.error("Preview failed: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"解析预览失败: {str(e)[:200]}",
        )
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


@router.post("")
async def upload_log(
    host_id: int,
    file: UploadFile = File(...),
    log_type: Optional[str] = Form(None),
    confirmed: bool = Form(True),
    current_user: dict = Depends(get_current_user),
):
    """上传日志文件并触发导入.

    支持 EVTX (.evtx)、Access Log (.log/.txt) 格式。
    可选指定 log_type 覆盖自动格式检测。
    如果 confirmed=False 表示预览模式，返回预览数据不入库。

    Args:
        host_id: 主机 ID.
        file: 上传的日志文件.
        log_type: （可选）指定日志类型，如 'evtx', 'nginx_access'.
        confirmed: 是否确认导入。False 则进入预览模式.
    """
    _get_host_or_404(host_id)

    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="文件名不能为空",
        )

    # 预览模式：confirmed=False
    if not confirmed:
        suffix = Path(file.filename).suffix or ".tmp"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name
        try:
            preview_data = _parse_preview(tmp_path, log_type or "auto", file.filename)
            return {
                "code": 0,
                "data": {
                    "file_name": file.filename,
                    "detected_format": preview_data["detected_format"],
                    "log_source": preview_data["log_source"],
                    "raw_fields": preview_data["raw_fields"],
                    "translated": preview_data["translated"],
                    "stats": preview_data["stats"],
                    "preview": True,
                },
                "message": "preview",
            }
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"解析预览失败: {str(e)[:200]}",
            )
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    # 确认模式：正常导入
    try:
        result = ImportLogService.import_file(host_id, file, log_type)
        return {"code": 0, "data": result, "message": "success"}
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get("/records")
def list_import_records(
    host_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    """获取主机的导入记录列表."""
    _get_host_or_404(host_id)

    records = ImportRecord.list_by_host(host_id)

    # 分页
    total = len(records)
    start = (page - 1) * page_size
    end = start + page_size
    paged = records[start:end]

    return {
        "code": 0,
        "data": {
            "items": paged,
            "total": total,
            "page": page,
            "page_size": page_size,
        },
        "message": "success",
    }


@router.get("/records/{record_id}")
def get_import_record(
    host_id: int,
    record_id: int,
    current_user: dict = Depends(get_current_user),
):
    """获取单条导入记录详情及结果明细."""
    _get_host_or_404(host_id)

    record = ImportRecord.get_by_id(record_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"导入记录 {record_id} 不存在",
        )

    # 获取结果明细
    results = ImportResult.list_by_import(record_id)

    return {
        "code": 0,
        "data": {
            "record": record,
            "results": results,
            "result_count": len(results),
        },
        "message": "success",
    }


@router.get("/tasks/{task_id}")
def get_task_status(
    host_id: int,
    task_id: str,
    current_user: dict = Depends(get_current_user),
):
    """查询异步导入任务状态.

    通过 task_id（即 record_id 的字符串形式）查询导入记录状态。

    Args:
        host_id: 主机 ID.
        task_id: 任务 ID（导入记录 ID 的字符串形式）.
    """
    _get_host_or_404(host_id)

    try:
        record_id = int(task_id)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="task_id 必须为整数",
        )

    record = ImportRecord.get_by_id(record_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"任务 {task_id} 不存在",
        )

    # 合并异步进度
    progress = ImportLogService.get_async_progress(task_id)

    return {
        "code": 0,
        "data": {
            "record_id": record["id"],
            "status": record.get("status", "unknown"),
            "file_name": record.get("file_name", ""),
            "log_type": record.get("log_type", ""),
            "parsed_count": record.get("parsed_count", 0),
            "event_count": record.get("event_count", 0),
            "error_message": record.get("error_message"),
            "created_at": record.get("created_at", ""),
            "progress": progress,
        },
        "message": "success",
    }
