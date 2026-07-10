"""主机差分基线模型（v1.3.0 支柱③）— agent_baselines 表 CRUD.

基线 JSON 约定（复用 v1.2.0 diff 产物语义）：
{ "known_items": { "<dimension>": [<signature>, ...] },
  "diff_new": [ ... ],
  "collection_health": {...} }
"""

import json
import logging
from typing import Optional

from app.database import get_connection

logger = logging.getLogger(__name__)


class AgentBaseline:
    """主机差分基线模型."""

    @staticmethod
    def create(
        host_id: int,
        baseline_json: dict,
        source: str = "uploaded",
        note: Optional[str] = None,
    ) -> dict:
        """创建一条基线记录.

        Args:
            host_id: 主机 ID.
            baseline_json: 基线数据字典（将序列化为 JSON 存储）.
            source: 来源 uploaded | agent_auto.
            note: 备注.

        Returns:
            创建的记录字典.
        """
        payload = baseline_json if isinstance(baseline_json, dict) else {}
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO agent_baselines
                (host_id, baseline_json, source, note, created_at)
                VALUES (?, ?, ?, ?, datetime('now'))
                """,
                (
                    host_id,
                    json.dumps(payload, ensure_ascii=False),
                    source,
                    note,
                ),
            )
            row_id = cursor.lastrowid
        return AgentBaseline.get_by_id(row_id)

    @staticmethod
    def get_by_id(row_id: int) -> Optional[dict]:
        """按 ID 获取基线记录."""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM agent_baselines WHERE id = ?", (row_id,)
            ).fetchone()
            return dict(row) if row else None

    @staticmethod
    def get_latest_by_host(host_id: int) -> Optional[dict]:
        """获取主机最新一条基线记录（R3-1 读取接口）."""
        with get_connection() as conn:
            row = conn.execute(
                """SELECT * FROM agent_baselines
                   WHERE host_id = ? ORDER BY created_at DESC, id DESC LIMIT 1""",
                (host_id,),
            ).fetchone()
            if not row:
                return None
            rec = dict(row)
            try:
                rec["baseline"] = json.loads(rec.get("baseline_json", "{}") or "{}")
            except (json.JSONDecodeError, TypeError):
                rec["baseline"] = {}
            return rec

    @staticmethod
    def list_by_host(host_id: int) -> list[dict]:
        """列出主机的所有基线记录（按时间倒序）."""
        with get_connection() as conn:
            rows = conn.execute(
                """SELECT * FROM agent_baselines
                   WHERE host_id = ? ORDER BY created_at DESC, id DESC""",
                (host_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def delete(row_id: int) -> None:
        """删除指定基线记录."""
        with get_connection() as conn:
            conn.execute("DELETE FROM agent_baselines WHERE id = ?", (row_id,))
