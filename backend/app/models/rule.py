"""Rule 数据模型 — 分析规则 CRUD."""

import json
import logging
from typing import Any, Optional

from app.database import get_connection

logger = logging.getLogger(__name__)


class Rule:
    """分析规则数据模型."""

    @staticmethod
    def create(name: str, category: str, rule_type: str,
               condition: dict, severity: str = "medium",
               description: Optional[str] = None, enabled: bool = True) -> dict:
        """创建规则."""
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO rules (name, description, category, rule_type, condition, severity, enabled)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    name,
                    description,
                    category,
                    rule_type,
                    json.dumps(condition, ensure_ascii=False),
                    severity,
                    1 if enabled else 0,
                ),
            )
            rule_id = cursor.lastrowid
        # Transaction committed after with block exits; query on a fresh connection
        return Rule.get_by_id(rule_id)

    @staticmethod
    def get_by_id(rule_id: int) -> Optional[dict]:
        """根据 ID 获取规则."""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM rules WHERE id = ?", (rule_id,)
            ).fetchone()
            if row:
                result = dict(row)
                if result.get("condition"):
                    try:
                        result["condition"] = json.loads(result["condition"])
                    except (json.JSONDecodeError, TypeError):
                        pass
                result["enabled"] = bool(result.get("enabled"))
                return result
            return None

    @staticmethod
    def list(category: Optional[str] = None, enabled: Optional[bool] = None) -> list:
        """获取规则列表（支持按类别和启用状态过滤）."""
        with get_connection() as conn:
            query = "SELECT * FROM rules WHERE 1=1"
            params: list = []
            if category:
                query += " AND category = ?"
                params.append(category)
            if enabled is not None:
                query += " AND enabled = ?"
                params.append(1 if enabled else 0)
            query += " ORDER BY category, severity DESC, created_at"
            rows = conn.execute(query, params).fetchall()
            results = []
            for row in rows:
                item = dict(row)
                if item.get("condition"):
                    try:
                        item["condition"] = json.loads(item["condition"])
                    except (json.JSONDecodeError, TypeError):
                        pass
                item["enabled"] = bool(item.get("enabled"))
                results.append(item)
            return results

    @staticmethod
    def list_enabled() -> list:
        """获取所有启用的规则."""
        return Rule.list(enabled=True)

    @staticmethod
    def update(rule_id: int, enabled: Optional[bool] = None,
               condition: Optional[dict] = None,
               severity: Optional[str] = None) -> Optional[dict]:
        """更新规则."""
        with get_connection() as conn:
            fields = []
            params: list = []
            if enabled is not None:
                fields.append("enabled = ?")
                params.append(1 if enabled else 0)
            if condition is not None:
                fields.append("condition = ?")
                params.append(json.dumps(condition, ensure_ascii=False))
            if severity is not None:
                fields.append("severity = ?")
                params.append(severity)
            if fields:
                fields.append("updated_at = datetime('now')")
                params.append(rule_id)
                conn.execute(
                    f"UPDATE rules SET {', '.join(fields)} WHERE id = ?",
                    params,
                )
        # Transaction committed after with block exits; query on a fresh connection
        return Rule.get_by_id(rule_id)

    @staticmethod
    def delete(rule_id: int) -> bool:
        """删除规则."""
        with get_connection() as conn:
            conn.execute("DELETE FROM rules WHERE id = ?", (rule_id,))
            return True
