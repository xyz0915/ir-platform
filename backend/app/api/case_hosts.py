"""案件→主机级联数据 API（供告警筛选使用）. """
import logging
from fastapi import APIRouter, Depends
from app.database import get_connection
from app.services.auth_service import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/cases/with-hosts")
def list_cases_with_hosts(current_user: dict = Depends(get_current_user)):
    """返回案件及下属主机列表，用于级联选择器."""
    try:
        with get_connection() as conn:
            cases = conn.execute(
                "SELECT id, name, case_number FROM cases ORDER BY created_at DESC"
            ).fetchall()
            result = []
            for c in cases:
                hosts = conn.execute(
                    "SELECT id, hostname, ip_address FROM hosts WHERE case_id=? ORDER BY hostname",
                    [c["id"]]
                ).fetchall()
                children = [
                    {"value": h["id"], "label": f"{h['hostname']} ({h['ip_address'] or 'N/A'})"}
                    for h in hosts
                ]
                result.append({
                    "value": c["id"],
                    "label": f"{c['name']} ({c['case_number'] or 'N/A'})",
                    "children": children,
                })
            return {"success": True, "data": result}
    except Exception as e:
        logger.error("Failed to list cases with hosts: %s", e)
        return {"success": False, "data": [], "error": str(e)}
