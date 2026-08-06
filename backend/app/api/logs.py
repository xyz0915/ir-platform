"""日志分析 API.

【P0-2 ACL】5 个端点统一注入可见主机集合；显式 host_id 越权 403。
【P1-1 时间】date_from/date_to 兼容 T/Z/毫秒格式（服务层 parse_client_time）。
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.models.normalized_log import NormalizedLog
from app.services.auth_service import get_current_user
from app.services.access_control import is_admin, resolve_allowed_host_ids, require_host_access

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/logs/search")
def search_logs(
    host_id: Optional[int] = Query(None),
    hostname: Optional[str] = Query(None),
    event_id: Optional[int] = Query(None),
    event_type: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    source_ip: Optional[str] = Query(None),
    user_name: Optional[str] = Query(None),
    process_name: Optional[str] = Query(None),
    logon_session: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    log_source: Optional[str] = Query(None),
    sort: str = Query("timestamp DESC"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
):
    allowed = resolve_allowed_host_ids(current_user, host_id)
    return {"success": True, "data": NormalizedLog.search(
        host_id=host_id, hostname=hostname,
        event_id=event_id, event_type=event_type, severity=severity,
        source_ip=source_ip, user_name=user_name,
        process_name=process_name, logon_session=logon_session,
        tag=tag, keyword=keyword,
        date_from=date_from, date_to=date_to, log_source=log_source,
        sort=sort, page=page, page_size=page_size,
        allowed_host_ids=allowed,
    )}


@router.get("/logs/stats/summary")
def log_stats(
    host_id: Optional[int] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    allowed = resolve_allowed_host_ids(current_user, host_id)
    return {"success": True, "data": NormalizedLog.get_stats(host_id=host_id, allowed_host_ids=allowed)}


@router.get("/logs/stats/timeline")
def log_timeline(
    host_id: Optional[int] = Query(None),
    interval: str = Query("hour"),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    allowed = resolve_allowed_host_ids(current_user, host_id)
    return {"success": True, "data": NormalizedLog.get_timeline(
        host_id=host_id, interval=interval, date_from=date_from, date_to=date_to,
        allowed_host_ids=allowed,
    )}


@router.get("/logs/session/{logon_session}")
def log_session(
    logon_session: str,
    current_user: dict = Depends(get_current_user),
):
    allowed = resolve_allowed_host_ids(current_user, None)
    return {"success": True, "data": NormalizedLog.get_session(logon_session, allowed_host_ids=allowed)}


@router.get("/logs/pivot")
def log_pivot(
    field: str = Query(...),
    value: str = Query(...),
    host_id: Optional[int] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    allowed = resolve_allowed_host_ids(current_user, host_id)
    return {"success": True, "data": NormalizedLog.pivot(field=field, value=value, host_id=host_id, allowed_host_ids=allowed)}


@router.get("/logs/patterns/brute-force")
def brute_force_patterns(
    min_attempts: int = Query(10),
    window_minutes: int = Query(5),
    host_id: Optional[int] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    allowed = resolve_allowed_host_ids(current_user, host_id)
    return {"success": True, "data": NormalizedLog.get_brute_force(
        min_attempts=min_attempts, window_minutes=window_minutes, host_id=host_id,
        allowed_host_ids=allowed,
    )}
