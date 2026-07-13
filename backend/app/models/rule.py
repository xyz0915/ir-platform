"""Rule 数据模型 — 分析规则 CRUD 与审计."""

import json
import logging
from typing import Any, Optional

from app.database import get_connection

logger = logging.getLogger(__name__)


class Rule:
    """分析规则数据模型."""

    # ── 工具：MITRE ATT&CK 顶层字段归一化（T-P2-3）──────────────
    @staticmethod
    def _normalize_mitre(row: dict) -> dict:
        """读取优先级：顶层 mitre_attack → condition._meta.mitre_attack → condition.mitre_attack.

        Args:
            row: 数据库行（dict，condition 已反序列化或仍为字符串）.

        Returns:
            写入归一化 mitre_attack 后的行.
        """
        condition = row.get("condition")
        if isinstance(condition, str):
            try:
                condition = json.loads(condition)
            except (json.JSONDecodeError, TypeError):
                condition = {}
        meta = condition.get("_meta", {}) if isinstance(condition, dict) else {}
        mitre = (
            row.get("mitre_attack")
            or (meta.get("mitre_attack") if isinstance(meta, dict) else None)
            or (condition.get("mitre_attack") if isinstance(condition, dict) else None)
        )
        row["mitre_attack"] = mitre
        return row

    @staticmethod
    def create(
        name: str,
        category: str,
        rule_type: str,
        condition: dict,
        severity: str = "medium",
        description: Optional[str] = None,
        enabled: bool = True,
        label: Optional[str] = None,
        source: str = "user",
        changed_by: Optional[str] = None,
    ) -> dict:
        """创建规则.

        Args:
            name: 规则英文技术键（唯一主键，被测试/引擎引用）.
            category: 类别.
            rule_type: 规则类型.
            condition: 条件字典.
            severity: 严重程度（critical/high/medium/low）.
            description: 描述.
            enabled: 是否启用.
            label: 中文展示名（本地化）.
            source: 来源 'default'（导入）| 'user'（API 创建）.
            changed_by: 操作人（来自 JWT）.
        """
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO rules
                    (name, description, category, rule_type, condition, severity, enabled, label, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    name,
                    description,
                    category,
                    rule_type,
                    json.dumps(condition, ensure_ascii=False),
                    severity,
                    1 if enabled else 0,
                    label,
                    source,
                ),
            )
            rule_id = cursor.lastrowid
        Rule._write_audit(
            rule_id,
            "create",
            changed_by,
            new_val=json.dumps(
                {"name": name, "severity": severity, "rule_type": rule_type},
                ensure_ascii=False,
            ),
        )
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
                return Rule._normalize_mitre(result)
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
                results.append(Rule._normalize_mitre(item))
            return results

    @staticmethod
    def list_enabled() -> list:
        """获取所有启用的规则."""
        return Rule.list(enabled=True)

    @staticmethod
    def search(category: Optional[str] = None, severity: Optional[str] = None,
               rule_type: Optional[str] = None, keyword: Optional[str] = None,
               page: int = 1, page_size: int = 100) -> dict:
        """规则多维度搜索（供策略规则选择器使用）. """
        with get_connection() as conn:
            conditions = ["1=1"]
            params = []
            if category:
                conditions.append("category=?")
                params.append(category)
            if severity:
                sevs = severity.split(",")
                placeholders = ",".join("?" for _ in sevs)
                conditions.append(f"severity IN ({placeholders})")
                params.extend(sevs)
            if rule_type:
                conditions.append("rule_type=?")
                params.append(rule_type)
            if keyword:
                conditions.append("(name LIKE ? OR description LIKE ? OR condition LIKE ?)")
                kw = f"%{keyword}%"
                params.extend([kw, kw, kw])
            where = " AND ".join(conditions)
            total = conn.execute(f"SELECT COUNT(*) FROM rules WHERE {where}", params).fetchone()[0]
            offset = (page - 1) * page_size
            rows = conn.execute(
                f"SELECT * FROM rules WHERE {where} ORDER BY severity DESC, category, name LIMIT ? OFFSET ?",
                params + [page_size, offset]
            ).fetchall()
            items = []
            for row in rows:
                item = dict(row)
                if item.get("condition"):
                    try:
                        item["condition"] = json.loads(item["condition"])
                    except (json.JSONDecodeError, TypeError):
                        pass
                item["enabled"] = bool(item.get("enabled"))
                items.append(item)
            return {"items": items, "total": total, "page": page, "page_size": page_size}

    @staticmethod
    def update(
        rule_id: int,
        enabled: Optional[bool] = None,
        condition: Optional[dict] = None,
        severity: Optional[str] = None,
        changed_by: Optional[str] = None,
    ) -> Optional[dict]:
        """更新规则（保持可改 severity/condition/enabled）并写审计."""
        existing = Rule.get_by_id(rule_id)
        if not existing:
            return None
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
        changes: dict[str, Any] = {}
        if enabled is not None:
            changes["enabled"] = enabled
        if condition is not None:
            changes["condition"] = condition
        if severity is not None:
            changes["severity"] = severity
        old_snapshot = {
            k: existing.get(k) for k in ("enabled", "condition", "severity")
        }
        Rule._write_audit(
            rule_id,
            "update",
            changed_by,
            old_val=json.dumps(old_snapshot, ensure_ascii=False, default=str),
            new_val=json.dumps(changes, ensure_ascii=False, default=str),
        )
        # Transaction committed after with block exits; query on a fresh connection
        return Rule.get_by_id(rule_id)

    @staticmethod
    def delete(rule_id: int, changed_by: Optional[str] = None) -> bool:
        """删除规则.

        守卫：仅 source='user' 的规则可被删除；source='default' 的默认规则
        不可删除（应使用「重置为默认」功能）。

        Raises:
            ValueError: 尝试删除默认规则时抛出.

        Returns:
            删除成功返回 True；规则不存在返回 False.
        """
        existing = Rule.get_by_id(rule_id)
        if not existing:
            return False
        if existing.get("source") == "default":
            raise ValueError("默认规则不可删除，请使用「重置为默认」功能")
        Rule._write_audit(
            rule_id,
            "delete",
            changed_by,
            old_val=json.dumps(
                {"name": existing.get("name"), "source": existing.get("source")},
                ensure_ascii=False,
            ),
        )
        with get_connection() as conn:
            conn.execute("DELETE FROM rules WHERE id = ?", (rule_id,))
            return True

    @staticmethod
    def _write_audit(
        rule_id: int,
        action: str,
        changed_by: Optional[str],
        old_val: Optional[str] = None,
        new_val: Optional[str] = None,
    ) -> None:
        """写入规则审计日志（T-P2-2），失败仅告警不阻塞主流程."""
        try:
            with get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO rule_audit_log
                        (rule_id, action, changed_by, old_val, new_val)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (rule_id, action, changed_by, old_val, new_val),
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("写入规则审计日志失败 (rule_id=%s): %s", rule_id, exc)
