"""AI 证据回填模型（v1.3.0 R2-3 只读派发）— ai_evidence_refills 表 CRUD.

readonly 采集子进程返回的证据 JSON 回填到此表，不触发 AI 重算、绝不自动处置。
"""

import json
import logging
from typing import Optional

from app.database import get_connection

logger = logging.getLogger(__name__)


class AiEvidenceRefill:
    """AI 证据回填模型."""

    @staticmethod
    def create(
        host_id: int,
        dispatch_task_id: int,
        evidence_json: dict,
        action_type: Optional[str] = None,
        target: Optional[str] = None,
        status: str = "completed",
    ) -> dict:
        """创建一条证据回填记录.

        Args:
            host_id: 主机 ID.
            dispatch_task_id: 派发任务 ID（对应派发表/任务）.
            evidence_json: 只读采集返回的证据字典.
            action_type: 动作类型.
            target: 作用对象.
            status: 采集状态（completed/partial/timeout/error）.

        Returns:
            创建的记录字典.
        """
        payload = evidence_json if isinstance(evidence_json, dict) else {}
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO ai_evidence_refills
                (host_id, dispatch_task_id, action_type, target, evidence_json, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (
                    host_id,
                    dispatch_task_id,
                    action_type,
                    target,
                    json.dumps(payload, ensure_ascii=False),
                    status,
                ),
            )
            row_id = cursor.lastrowid
        return AiEvidenceRefill.get_by_id(row_id)

    @staticmethod
    def get_by_id(row_id: int) -> Optional[dict]:
        """按 ID 获取回填记录."""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM ai_evidence_refills WHERE id = ?", (row_id,)
            ).fetchone()
            return dict(row) if row else None

    @staticmethod
    def list_by_host(host_id: int) -> list[dict]:
        """列出主机的所有证据回填记录（按时间倒序）."""
        with get_connection() as conn:
            rows = conn.execute(
                """SELECT * FROM ai_evidence_refills
                   WHERE host_id = ? ORDER BY created_at DESC, id DESC""",
                (host_id,),
            ).fetchall()
            result: list[dict] = []
            for r in rows:
                rec = dict(r)
                try:
                    rec["evidence"] = json.loads(rec.get("evidence_json", "{}") or "{}")
                except (json.JSONDecodeError, TypeError):
                    rec["evidence"] = {}
                result.append(rec)
            return result
