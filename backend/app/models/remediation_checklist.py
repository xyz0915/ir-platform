"""处置清单（Remediation Checklist）数据模型（任务⑤ 处置闭环）.

技术报告的处置清单复选框直接由前端勾选 PUT 落库（决策⑨ 无需二次复核）。
items 为 JSON 数组，元素结构：
    {id: str, text: str, checked: bool, source: 'ai'|'manual'}
"""

import json
import logging
from typing import Any, Dict, List, Optional

from app.database import get_connection

logger = logging.getLogger(__name__)


class RemediationChecklist:
    """处置清单 CRUD（静态方法，复用 get_connection）."""

    JSON_FIELDS = ("items",)

    @staticmethod
    def _row_to_dict(row) -> dict:
        result = dict(row)
        for field in RemediationChecklist.JSON_FIELDS:
            raw = result.get(field)
            if isinstance(raw, str) and raw:
                try:
                    result[field] = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    result[field] = []
            elif result.get(field) is None:
                result[field] = []
        return result

    @staticmethod
    def get_by_host(host_id: int) -> Optional[dict]:
        """获取某主机的处置清单（不存在返回 None）."""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM remediation_checklist WHERE host_id = ?",
                (host_id,),
            ).fetchone()
            if row:
                return RemediationChecklist._row_to_dict(row)
            return None

    @staticmethod
    def upsert(
        host_id: int,
        items: Optional[List[Dict[str, Any]]] = None,
        case_id: Optional[int] = None,
    ) -> dict:
        """创建或更新某主机的处置清单（按 host_id 唯一）.

        Args:
            host_id: 主机 ID。
            items: 处置清单项数组（全量覆盖）。缺省为空数组。
            case_id: 可选关联案件 ID。

        Returns:
            插入/更新后的记录 dict。
        """
        items = items or []
        # 为每个项补全默认字段
        normalized = [
            {
                "id": it.get("id") or f"item-{idx}",
                "text": it.get("text", ""),
                "checked": bool(it.get("checked", False)),
                "source": it.get("source", "manual"),
            }
            for idx, it in enumerate(items)
        ]

        existing = RemediationChecklist.get_by_host(host_id)
        with get_connection() as conn:
            if existing:
                conn.execute(
                    """
                    UPDATE remediation_checklist
                    SET items = ?, case_id = COALESCE(?, case_id),
                        updated_at = datetime('now')
                    WHERE host_id = ?
                    """,
                    (json.dumps(normalized, ensure_ascii=False), case_id, host_id),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO remediation_checklist (host_id, case_id, items)
                    VALUES (?, ?, ?)
                    """,
                    (host_id, case_id, json.dumps(normalized, ensure_ascii=False)),
                )
        return RemediationChecklist.get_by_host(host_id)

    @staticmethod
    def update_items(host_id: int, items: List[Dict[str, Any]]) -> dict:
        """全量覆盖某主机的处置清单项（PUT 语义，决策⑨）."""
        return RemediationChecklist.upsert(host_id, items=items)
