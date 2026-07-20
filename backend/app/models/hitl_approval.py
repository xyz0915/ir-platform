"""人在回路审批模型 — hitl_approvals 表 CRUD（§4.1 / §8.4）."""

import json
import logging
from typing import Any, Optional

from app.database import get_connection

logger = logging.getLogger(__name__)


class HitlApproval:
    """HITL 审批表 CRUD。"""

    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_EXPIRED = "expired"

    @staticmethod
    def create(
        run_id: str,
        action: str,
        requested_by: Optional[int] = None,
        step_id: Optional[int] = None,
        target_json: Optional[dict] = None,
        auto_rollback_plan: Optional[dict] = None,
        reason: Optional[str] = None,
    ) -> dict:
        """创建一条待审批记录（status=pending）。"""
        def _j(v: Any) -> str:
            if v is None:
                return "{}"
            if isinstance(v, (dict, list)):
                return json.dumps(v, ensure_ascii=False, default=str)
            return str(v)

        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO hitl_approvals
                (run_id, step_id, action, target_json, requested_by, status,
                 auto_rollback_plan, reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (run_id, step_id, action, _j(target_json), requested_by,
                 HitlApproval.STATUS_PENDING, _j(auto_rollback_plan), reason),
            )
            aid = cursor.lastrowid
            row = conn.execute(
                "SELECT * FROM hitl_approvals WHERE id = ?", (aid,)
            ).fetchone()
        return dict(row)

    @staticmethod
    def get_by_id(aid: int) -> Optional[dict]:
        """按主键获取。"""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM hitl_approvals WHERE id = ?", (aid,)
            ).fetchone()
            return dict(row) if row else None

    @staticmethod
    def update_status(
        aid: int,
        status: str,
        decided_by: Optional[int] = None,
        reason: Optional[str] = None,
    ) -> Optional[dict]:
        """决议：approve（仅 admin）/reject → 写 decided_by/decided_at。"""
        allowed = {
            HitlApproval.STATUS_APPROVED,
            HitlApproval.STATUS_REJECTED,
            HitlApproval.STATUS_EXPIRED,
        }
        if status not in allowed:
            raise ValueError(f"非法审批状态: {status}")

        with get_connection() as conn:
            if reason is not None:
                conn.execute(
                    """
                    UPDATE hitl_approvals
                    SET status = ?, decided_by = ?, decided_at = datetime('now'),
                        reason = ?, updated_at = datetime('now')
                    WHERE id = ?
                    """,
                    (status, decided_by, reason, aid),
                )
            else:
                conn.execute(
                    """
                    UPDATE hitl_approvals
                    SET status = ?, decided_by = ?, decided_at = datetime('now'),
                        updated_at = datetime('now')
                    WHERE id = ?
                    """,
                    (status, decided_by, aid),
                )
            row = conn.execute(
                "SELECT * FROM hitl_approvals WHERE id = ?", (aid,)
            ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def list_by_run(run_id: str) -> list[dict]:
        """列出某 run 的审批记录。"""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM hitl_approvals WHERE run_id = ? ORDER BY id ASC",
                (run_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def list_pending(page: int = 1, page_size: int = 50) -> dict:
        """列出所有待审批记录（admin 面板用）。"""
        with get_connection() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM hitl_approvals WHERE status = ?",
                (HitlApproval.STATUS_PENDING,),
            ).fetchone()[0]
            offset = (page - 1) * page_size
            rows = conn.execute(
                "SELECT * FROM hitl_approvals WHERE status = ? "
                "ORDER BY created_at ASC LIMIT ? OFFSET ?",
                (HitlApproval.STATUS_PENDING, page_size, offset),
            ).fetchall()
        return {
            "items": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
