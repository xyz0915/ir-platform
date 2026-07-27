from __future__ import annotations

"""默认闭环规则表 CRUD — pipeline_default_rules.

设计（config-default-pipeline PRD/架构 §3.1）：规则与 pipeline_presets 解耦，
一条规则 = 「一个 preset_id + 一组场景条件(scene_condition JSON)」。
支持多条场景规则引用同一 pipeline（Q7），以及至多一条全局默认（is_global=1）。
"""

import json
import logging
from typing import Any, Optional

from app.database import get_connection

logger = logging.getLogger(__name__)


def _j(value: Any) -> str:
    """将 Python 对象序列化为 JSON 字符串."""
    if value is None:
        return "{}"
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def _d(value: Any, default: Any = None) -> Any:
    """将 JSON 字符串反序列化为 Python 对象."""
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


class PipelineDefaultRuleModel:
    """pipeline_default_rules 规则表 CRUD."""

    @staticmethod
    def create(data: dict) -> dict:
        """创建一条默认规则.

        Args:
            data: {preset_id, name?, scene_condition?, is_global?, priority_order?, created_by?}

        Returns:
            新建的规则行（dict，scene_condition 已解析为 dict）。
        """
        scene_condition = data.get("scene_condition", {}) or {}
        is_global = 1 if data.get("is_global") else 0
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO pipeline_default_rules
                    (preset_id, name, scene_condition, is_global, priority_order, created_by)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    data["preset_id"],
                    data.get("name") or None,
                    _j(scene_condition),
                    is_global,
                    data.get("priority_order", 0) or 0,
                    data.get("created_by") or None,
                ),
            )
            rid = cursor.lastrowid
        return PipelineDefaultRuleModel.get(rid)

    @staticmethod
    def get(rule_id: int) -> Optional[dict]:
        """按主键查询规则."""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM pipeline_default_rules WHERE id = ?", (rule_id,)
            ).fetchone()
            if not row:
                return None
            return PipelineDefaultRuleModel._row_to_dict(row)

    @staticmethod
    def list() -> list[dict]:
        """列出全部规则（全局默认优先，其次按 priority_order 升序）。"""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM pipeline_default_rules "
                "ORDER BY is_global DESC, priority_order ASC, id ASC"
            ).fetchall()
        return [PipelineDefaultRuleModel._row_to_dict(r) for r in rows]

    @staticmethod
    def list_by_preset(preset_id: int) -> list[dict]:
        """列出引用某 preset 的全部规则（Q7：多规则指向同一 pipeline）."""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM pipeline_default_rules WHERE preset_id = ?", (preset_id,)
            ).fetchall()
        return [PipelineDefaultRuleModel._row_to_dict(r) for r in rows]

    @staticmethod
    def list_global() -> list[dict]:
        """列出全局默认规则（正常至多 1 条）."""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM pipeline_default_rules WHERE is_global = 1"
            ).fetchall()
        return [PipelineDefaultRuleModel._row_to_dict(r) for r in rows]

    @staticmethod
    def update(rule_id: int, updates: dict) -> Optional[dict]:
        """局部更新规则（name/scene_condition/is_global/priority_order）.

        返回更新后的规则行；updates 为空时返回原记录。
        """
        allowed = {"name", "scene_condition", "is_global", "priority_order"}
        data: dict[str, Any] = {}
        for k in allowed:
            if k not in updates:
                continue
            v = updates[k]
            if k == "scene_condition":
                data[k] = _j(v)
            elif k == "is_global":
                data[k] = 1 if v else 0
            else:
                data[k] = v
        if not data:
            return PipelineDefaultRuleModel.get(rule_id)
        clauses = [f"{k} = ?" for k in data]
        values = list(data.values())
        values.append(rule_id)
        with get_connection() as conn:
            conn.execute(
                f"UPDATE pipeline_default_rules SET {', '.join(clauses)}, "
                f"updated_at = datetime('now') WHERE id = ?",
                values,
            )
        return PipelineDefaultRuleModel.get(rule_id)

    @staticmethod
    def delete(rule_id: int) -> bool:
        """删除规则."""
        with get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM pipeline_default_rules WHERE id = ?", (rule_id,)
            )
            return cursor.rowcount > 0

    @staticmethod
    def _row_to_dict(row) -> dict:
        """将一行转为 dict，并解析 scene_condition / is_global."""
        d = dict(row)
        d["scene_condition"] = _d(d.get("scene_condition"), {})
        d["is_global"] = bool(d.get("is_global"))
        return d
