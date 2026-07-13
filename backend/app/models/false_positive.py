"""误报自学习模式模型."""

from app.database import get_connection


class FalsePositivePattern:

    @staticmethod
    def create(rule_name: str, source_process: str = "", source_ip: str = "",
               host_id: int = 0, reason: str = "", created_by: str = "") -> int:
        try:
            with get_connection() as conn:
                cur = conn.execute(
                    """INSERT INTO false_positive_patterns
                       (rule_name, source_process, source_ip, host_id, reason, created_by)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    [rule_name, source_process, source_ip, host_id, reason, created_by]
                )
                conn.commit()
                return cur.lastrowid or 0
        except Exception:
            return 0

    @staticmethod
    def match(rule_name: str, source_process: str = "", host_id: int = 0) -> bool:
        """检查是否匹配已有误报模式. 匹配则 increment hit_count."""
        try:
            with get_connection() as conn:
                rows = conn.execute(
                    """SELECT id FROM false_positive_patterns
                       WHERE rule_name=? AND (source_process=? OR source_process='')
                       AND (host_id=? OR host_id=0) LIMIT 1""",
                    [rule_name, source_process, host_id]
                ).fetchone()
                if rows:
                    conn.execute("UPDATE false_positive_patterns SET hit_count=hit_count+1 WHERE id=?",
                                 [rows["id"]])
                    conn.commit()
                    return True
                return False
        except Exception:
            return False

    @staticmethod
    def list(page: int = 1, page_size: int = 50) -> dict:
        try:
            with get_connection() as conn:
                total = conn.execute("SELECT COUNT(*) FROM false_positive_patterns").fetchone()[0]
                offset = (page - 1) * page_size
                rows = conn.execute(
                    "SELECT * FROM false_positive_patterns ORDER BY hit_count DESC, created_at DESC LIMIT ? OFFSET ?",
                    [page_size, offset]
                ).fetchall()
                return {"items": [dict(r) for r in rows], "total": total, "page": page, "page_size": page_size}
        except Exception:
            return {"items": [], "total": 0, "page": page, "page_size": page_size}

    @staticmethod
    def delete(pattern_id: int) -> bool:
        try:
            with get_connection() as conn:
                conn.execute("DELETE FROM false_positive_patterns WHERE id=?", [pattern_id])
                conn.commit()
                return True
        except Exception:
            return False
