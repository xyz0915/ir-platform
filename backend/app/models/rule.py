"""Rule 数据模型 — 分析规则 CRUD 与审计."""

import json
import logging
from datetime import datetime
from typing import Any, Optional, List

from app.database import get_connection

logger = logging.getLogger(__name__)


class RuleHistory:
    """规则版本历史数据模型（T-P1-1）."""

    @staticmethod
    def create(rule_id: int, version: int, snapshot: str, action: str,
               operator: str, comment: str = "", approved_by: str = "") -> int:
        """创建规则历史记录."""
        with get_connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO rule_history
                    (rule_id, version, snapshot, action, operator, comment, approved_by)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (rule_id, version, snapshot, action, operator, comment, approved_by),
            )
            return cur.lastrowid or 0

    @staticmethod
    def list_by_rule(rule_id: int) -> list:
        """获取指定规则的版本历史（version 降序）."""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM rule_history WHERE rule_id = ? ORDER BY version DESC",
                (rule_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def get_version(rule_id: int, version: int) -> Optional[dict]:
        """获取指定规则的指定版本快照."""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM rule_history WHERE rule_id = ? AND version = ?",
                (rule_id, version),
            ).fetchone()
            return dict(row) if row else None


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
    def list(category: Optional[str] = None, enabled: Optional[bool] = None,
             tenant_id: Optional[int] = None) -> list:
        """获取规则列表（支持按类别、启用状态过滤 + 多租户隔离）.

        Args:
            category: 规则类别过滤.
            enabled: 启用状态过滤.
            tenant_id: 租户 ID（T-P2-1）。若 >0 则添加 ``WHERE tenant_id=? OR tenant_id=0``.
        """
        with get_connection() as conn:
            query = "SELECT * FROM rules WHERE 1=1"
            params: list = []
            if tenant_id is not None and tenant_id > 0:
                query += " AND (tenant_id = ? OR tenant_id = 0)"
                params.append(tenant_id)
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
    def list_by_ids(rule_ids: List[int]) -> list:
        """按ID列表批量获取启用的规则."""
        if not rule_ids:
            return []
        placeholders = ",".join("?" for _ in rule_ids)
        with get_connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM rules WHERE id IN ({placeholders}) AND enabled=1",
                rule_ids
            ).fetchall()
            results = []
            for row in rows:
                item = dict(row)
                item["enabled"] = bool(item.get("enabled"))
                results.append(Rule._normalize_mitre(item))
            return results

    @staticmethod
    def list_categories(categories: list, enabled: Optional[bool] = None) -> list:
        """按多个类别批量获取规则（供 RuleEngine.load_rules_by_categories 使用）."""
        if not categories:
            return []
        placeholders = ",".join("?" for _ in categories)
        query = f"SELECT * FROM rules WHERE category IN ({placeholders})"
        params: list = list(categories)
        if enabled is not None:
            query += " AND enabled = ?"
            params.append(1 if enabled else 0)
        query += " ORDER BY category, severity DESC, created_at"
        with get_connection() as conn:
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
        description: Optional[str] = None,
        owner: Optional[str] = None,
        name: Optional[str] = None,
        label: Optional[str] = None,
        mitre_attack: Optional[str] = None,
    ) -> Optional[dict]:
        """更新规则（保持可改 severity/condition/enabled）并写审计和版本历史.

        T-P1-1: 每次更新写 rule_history 快照，version 递增。
        T-P2-2a: 新增 name/label/mitre_attack/owner 可编辑字段。
        """
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
            if description is not None:
                fields.append("description = ?")
                params.append(description)
            if owner is not None:
                fields.append("owner = ?")
                params.append(owner)
            if name is not None:
                fields.append("name = ?")
                params.append(name)
            if label is not None:
                fields.append("label = ?")
                params.append(label)
            if mitre_attack is not None:
                fields.append("mitre_attack = ?")
                params.append(mitre_attack)
            if fields:
                fields.append("version = version + 1")
                fields.append("updated_at = datetime('now')")
                params.append(rule_id)
                conn.execute(
                    f"UPDATE rules SET {', '.join(fields)} WHERE id = ?",
                    params,
                )
                # T-P1-1: 写 rule_history 快照
                new_row = conn.execute(
                    "SELECT * FROM rules WHERE id = ?", (rule_id,)
                ).fetchone()
                if new_row:
                    try:
                        nr = dict(new_row)
                        new_version = nr["version"]
                        snapshot = json.dumps(
                            {
                                "version": new_version,
                                "name": nr.get("name"),
                                "condition": nr.get("condition"),
                                "severity": nr.get("severity"),
                                "category": nr.get("category"),
                                "rule_type": nr.get("rule_type"),
                                "status": nr.get("status", "active"),
                                "enabled": bool(nr.get("enabled")),
                                "approved_by": nr.get("approved_by"),
                                "owner": nr.get("owner"),
                                "saved_at": datetime.now().isoformat(),
                            },
                            ensure_ascii=False, default=str,
                        )
                        conn.execute(
                            """
                            INSERT INTO rule_history
                                (rule_id, version, snapshot, action, operator, comment)
                            VALUES (?, ?, ?, 'update', ?, '')
                            """,
                            (rule_id, new_version, snapshot, changed_by or "system"),
                        )
                    except Exception as exc:
                        logger.warning("写入 rule_history 快照失败: %s", exc)
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

    # ── T-P1-1 生命周期管理 ─────────────────────────────────────

    @staticmethod
    def approve(rule_id: int, approved_by: str) -> Optional[dict]:
        """审批规则（admin 角色），更新 status='active'，写入 approved_by."""
        existing = Rule.get_by_id(rule_id)
        if not existing:
            return None
        with get_connection() as conn:
            conn.execute(
                "UPDATE rules SET status = 'active', approved_by = ?, version = version + 1, updated_at = datetime('now') WHERE id = ?",
                (approved_by, rule_id),
            )
            # 写 rule_history
            new_row = conn.execute("SELECT * FROM rules WHERE id = ?", (rule_id,)).fetchone()
            if new_row:
                nr = dict(new_row)
                new_version = nr["version"]
                snapshot = json.dumps({
                    "version": new_version,
                    "name": nr.get("name"),
                    "condition": nr.get("condition"),
                    "severity": nr.get("severity"),
                    "category": nr.get("category"),
                    "rule_type": nr.get("rule_type"),
                    "status": "active",
                    "enabled": bool(nr.get("enabled")),
                    "approved_by": approved_by,
                    "owner": nr.get("owner"),
                    "saved_at": datetime.now().isoformat(),
                }, ensure_ascii=False, default=str)
                conn.execute(
                    "INSERT INTO rule_history (rule_id, version, snapshot, action, operator, comment, approved_by) VALUES (?, ?, ?, 'approve', ?, '', ?)",
                    (rule_id, new_version, snapshot, approved_by, approved_by),
                )
        Rule._write_audit(rule_id, "approve", approved_by,
                          new_val=json.dumps({"status": "active", "approved_by": approved_by}))
        return Rule.get_by_id(rule_id)

    @staticmethod
    def revert(rule_id: int, target_version: int, changed_by: str) -> Optional[dict]:
        """回滚规则到指定版本，取 rule_history.snapshot JSON 回写字段."""
        existing = Rule.get_by_id(rule_id)
        if not existing:
            return None
        history = RuleHistory.get_version(rule_id, target_version)
        if not history:
            raise ValueError(f"版本 {target_version} 不存在")
        snapshot_str = history["snapshot"]
        try:
            snapshot = json.loads(snapshot_str) if isinstance(snapshot_str, str) else {}
        except (json.JSONDecodeError, TypeError):
            raise ValueError(f"版本 {target_version} 快照数据异常")
        condition = snapshot.get("condition", "{}")
        severity = snapshot.get("severity", "medium")
        with get_connection() as conn:
            conn.execute(
                "UPDATE rules SET condition = ?, severity = ?, version = version + 1, updated_at = datetime('now') WHERE id = ?",
                (condition, severity, rule_id),
            )
            new_row = conn.execute("SELECT * FROM rules WHERE id = ?", (rule_id,)).fetchone()
            if new_row:
                nr = dict(new_row)
                new_version = nr["version"]
                cur_snapshot = json.dumps({
                    "version": new_version,
                    "name": nr.get("name"),
                    "condition": nr.get("condition"),
                    "severity": nr.get("severity"),
                    "category": nr.get("category"),
                    "rule_type": nr.get("rule_type"),
                    "status": nr.get("status", "active"),
                    "enabled": bool(nr.get("enabled")),
                    "approved_by": nr.get("approved_by"),
                    "owner": nr.get("owner"),
                    "saved_at": datetime.now().isoformat(),
                }, ensure_ascii=False, default=str)
                conn.execute(
                    "INSERT INTO rule_history (rule_id, version, snapshot, action, operator, comment) VALUES (?, ?, ?, 'revert', ?, ?)",
                    (rule_id, new_version, cur_snapshot, changed_by, f"回滚到版本 {target_version}"),
                )
        Rule._write_audit(rule_id, "revert", changed_by,
                          old_val=snapshot_str,
                          new_val=json.dumps({"reverted_to_version": target_version}))
        return Rule.get_by_id(rule_id)

    @staticmethod
    def deprecate(rule_id: int, changed_by: str) -> Optional[dict]:
        """标记规则为 deprecated."""
        existing = Rule.get_by_id(rule_id)
        if not existing:
            return None
        with get_connection() as conn:
            conn.execute(
                "UPDATE rules SET status = 'deprecated', deprecated_at = datetime('now'), version = version + 1, updated_at = datetime('now') WHERE id = ?",
                (rule_id,),
            )
            new_row = conn.execute("SELECT * FROM rules WHERE id = ?", (rule_id,)).fetchone()
            if new_row:
                nr = dict(new_row)
                new_version = nr["version"]
                snapshot = json.dumps({
                    "version": new_version,
                    "name": nr.get("name"),
                    "condition": nr.get("condition"),
                    "severity": nr.get("severity"),
                    "category": nr.get("category"),
                    "rule_type": nr.get("rule_type"),
                    "status": "deprecated",
                    "enabled": bool(nr.get("enabled")),
                    "deprecated_at": nr.get("deprecated_at"),
                    "saved_at": datetime.now().isoformat(),
                }, ensure_ascii=False, default=str)
                conn.execute(
                    "INSERT INTO rule_history (rule_id, version, snapshot, action, operator, comment) VALUES (?, ?, ?, 'deprecate', ?, ?)",
                    (rule_id, new_version, snapshot, changed_by, "标记为已废弃"),
                )
        Rule._write_audit(rule_id, "deprecate", changed_by)
        return Rule.get_by_id(rule_id)

    @staticmethod
    def list_history(rule_id: int) -> list:
        """获取指定规则的版本历史（version 降序）."""
        return RuleHistory.list_by_rule(rule_id)
