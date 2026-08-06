"""案件→主机级联数据 API（供告警筛选使用）. """
import logging
from fastapi import APIRouter, Depends
from app.database import get_connection
from app.services.auth_service import get_current_user
from app.services.access_control import get_visible_case_ids, get_visible_host_ids

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/cases/with-hosts")
def list_cases_with_hosts(current_user: dict = Depends(get_current_user)):
    """返回案件及下属主机列表（含统计数据），用于级联选择器.

    【P0-2 ACL】admin 全量；非 admin 仅返回被授权案件及其主机。
    """
    try:
        visible_cases = get_visible_case_ids(current_user)
        visible_hosts = get_visible_host_ids(current_user)

        with get_connection() as conn:
            # 1. 查案件（ACL 过滤）
            if visible_cases is None:
                cases = conn.execute(
                    "SELECT id, name, case_number FROM cases ORDER BY created_at DESC"
                ).fetchall()
            else:
                if not visible_cases:
                    return {"success": True, "data": []}
                placeholders = ",".join("?" for _ in visible_cases)
                cases = conn.execute(
                    f"SELECT id, name, case_number FROM cases WHERE id IN ({placeholders}) "
                    "ORDER BY created_at DESC",
                    sorted(visible_cases),
                ).fetchall()
            if not cases:
                return {"success": True, "data": []}

            case_ids = [c["id"] for c in cases]

            # 2. 查主机（按 case 分组；ACL 再按可见主机过滤）
            case_placeholders = ",".join("?" for _ in case_ids)
            if visible_hosts is None:
                hosts = conn.execute(
                    f"SELECT id, hostname, ip_address, case_id FROM hosts "
                    f"WHERE case_id IN ({case_placeholders}) ORDER BY hostname",
                    case_ids
                ).fetchall()
            else:
                if not visible_hosts:
                    return {"success": True, "data": []}
                host_placeholders = ",".join("?" for _ in visible_hosts)
                hosts = conn.execute(
                    f"SELECT id, hostname, ip_address, case_id FROM hosts "
                    f"WHERE case_id IN ({case_placeholders}) "
                    f"AND id IN ({host_placeholders}) ORDER BY hostname",
                    case_ids + sorted(visible_hosts),
                ).fetchall()

            # 3. 单次聚合：每个 case 的 log_count（agent_imports）
            case_log_counts = dict(
                conn.execute(f"""
                    SELECT h.case_id, COALESCE(SUM(ai.item_count), 0) AS cnt
                    FROM agent_imports ai
                    JOIN hosts h ON ai.host_id = h.id
                    WHERE h.case_id IN ({case_placeholders})
                    GROUP BY h.case_id
                """, case_ids).fetchall()
            )

            # 4. 单次聚合：每个 case 的 event_count（security_events）
            case_event_counts = dict(
                conn.execute(f"""
                    SELECT h.case_id, COUNT(se.id) AS cnt
                    FROM security_events se
                    JOIN hosts h ON se.host_id = h.id
                    WHERE h.case_id IN ({case_placeholders})
                    GROUP BY h.case_id
                """, case_ids).fetchall()
            )

            # 5. 单次聚合：每个 host 的 log_count
            host_ids = [h["id"] for h in hosts]
            host_log_counts: dict[int, int] = {}
            host_event_counts: dict[int, int] = {}
            if host_ids:
                host_placeholders = ",".join("?" for _ in host_ids)
                host_log_counts = dict(
                    conn.execute(f"""
                        SELECT host_id, COALESCE(SUM(item_count), 0) AS cnt FROM agent_imports
                        WHERE host_id IN ({host_placeholders})
                        GROUP BY host_id
                    """, host_ids).fetchall()
                )
                # 6. 单次聚合：每个 host 的 event_count
                host_event_counts = dict(
                    conn.execute(f"""
                        SELECT host_id, COUNT(*) AS cnt FROM security_events
                        WHERE host_id IN ({host_placeholders})
                        GROUP BY host_id
                    """, host_ids).fetchall()
                )

            # 7. 组装结果
            host_map: dict[int, list[dict]] = {}
            for h in hosts:
                host_map.setdefault(h["case_id"], []).append({
                    "value": h["id"],
                    "label": f"{h['hostname']} ({h['ip_address'] or 'N/A'})",
                    "hostname": h["hostname"],
                    "ip": h["ip_address"],
                    "log_count": host_log_counts.get(h["id"], 0),
                    "event_count": host_event_counts.get(h["id"], 0),
                })

            result = [
                {
                    "value": c["id"],
                    "name": c["name"],
                    "case_number": c["case_number"],
                    "label": f"{c['name']} ({c['case_number'] or 'N/A'})",
                    "log_count": case_log_counts.get(c["id"], 0),
                    "event_count": case_event_counts.get(c["id"], 0),
                    "children": host_map.get(c["id"], []),
                }
                for c in cases
            ]
            return {"success": True, "data": result}
    except Exception as e:
        logger.error("Failed to list cases with hosts: %s", e)
        return {"success": False, "data": [], "error": str(e)}
