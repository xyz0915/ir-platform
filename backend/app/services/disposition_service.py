import logging
from typing import Optional

from app.database import get_connection

logger = logging.getLogger(__name__)


def add_disposition(event_id: str, action: str, operator: str = "", comment: str = "") -> dict:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO event_disposition_log (event_id, action, operator, comment) VALUES (?, ?, ?, ?)",
            (event_id, action, operator, comment),
        )
        row = conn.execute(
            "SELECT * FROM event_disposition_log WHERE id = last_insert_rowid()"
        ).fetchone()
        return dict(row)


def get_dispositions(event_id: str, limit: int = 50, offset: int = 0) -> dict:
    with get_connection() as conn:
        total = conn.execute(
            "SELECT COUNT(*) as cnt FROM event_disposition_log WHERE event_id=?",
            (event_id,),
        ).fetchone()["cnt"]
        rows = conn.execute(
            "SELECT * FROM event_disposition_log WHERE event_id=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (event_id, limit, offset),
        ).fetchall()
        return {"items": [dict(r) for r in rows], "total": total}
