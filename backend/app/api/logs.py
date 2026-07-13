"""日志分析 API."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.models.normalized_log import NormalizedLog
from app.services.auth_service import get_current_user

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
    return {"success": True, "data": NormalizedLog.search(
        host_id=host_id, hostname=hostname,
        event_id=event_id, event_type=event_type, severity=severity,
        source_ip=source_ip, user_name=user_name,
        process_name=process_name, logon_session=logon_session,
        tag=tag, keyword=keyword,
        date_from=date_from, date_to=date_to, log_source=log_source,
        sort=sort, page=page, page_size=page_size,
    )}


@router.get("/logs/stats/summary")
def log_stats(
    host_id: Optional[int] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    return {"success": True, "data": NormalizedLog.get_stats(host_id=host_id)}


@router.get("/logs/stats/timeline")
def log_timeline(
    host_id: Optional[int] = Query(None),
    interval: str = Query("hour"),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    return {"success": True, "data": NormalizedLog.get_timeline(
        host_id=host_id, interval=interval, date_from=date_from, date_to=date_to,
    )}


@router.get("/logs/session/{logon_session}")
def log_session(
    logon_session: str,
    current_user: dict = Depends(get_current_user),
):
    return {"success": True, "data": NormalizedLog.get_session(logon_session)}


@router.get("/logs/pivot")
def log_pivot(
    field: str = Query(...),
    value: str = Query(...),
    host_id: Optional[int] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    return {"success": True, "data": NormalizedLog.pivot(field=field, value=value, host_id=host_id)}


@router.get("/logs/patterns/brute-force")
def brute_force_patterns(
    min_attempts: int = Query(10),
    window_minutes: int = Query(5),
    host_id: Optional[int] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    return {"success": True, "data": NormalizedLog.get_brute_force(
        min_attempts=min_attempts, window_minutes=window_minutes, host_id=host_id,
    )}
