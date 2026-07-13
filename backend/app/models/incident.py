"""事件归并模型."""

import json
from datetime import datetime
from app.database import get_connection


class IncidentCorrelation:

    @staticmethod
    def create(title: str, description: str, severity: str = "medium",
               host_ids: list = None, alert_ids: list = None,
               timeline_json: list = None, kill_chain: str = "",
               mitre_ids: list = None, recommendations: str = "") -> int:
        try:
            with get_connection() as conn:
                cur = conn.execute(
                    """INSERT INTO incident_correlations
                       (title, description, severity, host_ids, alert_ids,
                        timeline_json, kill_chain, mitre_ids, recommendations)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [title, description, severity,
                     json.dumps(host_ids or [], ensure_ascii=False),
                     json.dumps(alert_ids or [], ensure_ascii=False),
                     json.dumps(timeline_json or [], ensure_ascii=False),
                     kill_chain,
                     json.dumps(mitre_ids or [], ensure_ascii=False),
                     recommendations]
                )
                conn.commit()
                return cur.lastrowid or 0
        except Exception as e:
            return 0

    @staticmethod
    def get_all(page: int = 1, page_size: int = 20) -> dict:
        try:
            with get_connection() as conn:
                total = conn.execute("SELECT COUNT(*) FROM incident_correlations").fetchone()[0]
                offset = (page - 1) * page_size
                rows = conn.execute(
                    "SELECT * FROM incident_correlations ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    [page_size, offset]
                ).fetchall()
                items = []
                for r in rows:
                    d = dict(r)
                    for field in ("host_ids", "alert_ids", "timeline_json", "mitre_ids"):
                        try:
                            d[field] = json.loads(d[field]) if d.get(field) else []
                        except (json.JSONDecodeError, TypeError):
                            d[field] = []
                    items.append(d)
                return {"items": items, "total": total, "page": page, "page_size": page_size}
        except Exception:
            return {"items": [], "total": 0, "page": page, "page_size": page_size}

    @staticmethod
    def get_by_id(cid: int) -> dict:
        try:
            with get_connection() as conn:
                row = conn.execute("SELECT * FROM incident_correlations WHERE id=?", [cid]).fetchone()
                if not row:
                    return {}
                d = dict(row)
                for field in ("host_ids", "alert_ids", "timeline_json", "mitre_ids"):
                    try:
                        d[field] = json.loads(d[field]) if d.get(field) else []
                    except (json.JSONDecodeError, TypeError):
                        d[field] = []
                return d
        except Exception:
            return {}
