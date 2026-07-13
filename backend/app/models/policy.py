"""检测策略模型 (DetectionPolicy)."""

import logging
from datetime import datetime
from typing import Optional

from app.database import get_connection

logger = logging.getLogger(__name__)


class DetectionPolicy:

    @staticmethod
    def create(name: str, description: str = "", enable_rag: int = 0,
               enable_attack_chain: int = 0, tags: str = "", parent_id: Optional[int] = None) -> Optional[int]:
        """创建策略."""
        try:
            with get_connection() as conn:
                cur = conn.execute(
                    """INSERT INTO detection_policies (name, description, enable_rag, enable_attack_chain, tags, parent_id)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    [name, description, enable_rag, enable_attack_chain, tags, parent_id]
                )
                conn.commit()
                return cur.lastrowid
        except Exception as e:
            logger.error("Policy.create failed: %s", e)
            return None

    @staticmethod
    def get_all() -> list[dict]:
        """获取所有策略."""
        try:
            with get_connection() as conn:
                rows = conn.execute(
                    """SELECT p.*, (SELECT COUNT(*) FROM policy_rules WHERE policy_id=p.id) as rule_count
                       FROM detection_policies p ORDER BY p.created_at DESC"""
                ).fetchall()
                return [dict(r) for r in rows]
        except Exception as e:
            logger.error("Policy.get_all failed: %s", e)
            return []

    @staticmethod
    def get_by_id(policy_id: int) -> Optional[dict]:
        """获取策略详情（含规则列表）."""
        try:
            with get_connection() as conn:
                row = conn.execute(
                    """SELECT p.*, (SELECT COUNT(*) FROM policy_rules WHERE policy_id=p.id) as rule_count
                       FROM detection_policies p WHERE p.id=?""",
                    [policy_id]
                ).fetchone()
                if not row:
                    return None
                result = dict(row)
                # 获取关联规则
                rules = conn.execute(
                    """SELECT r.* FROM rules r
                       JOIN policy_rules pr ON pr.rule_id=r.id
                       WHERE pr.policy_id=? ORDER BY r.category, r.name""",
                    [policy_id]
                ).fetchall()
                result["rules"] = [dict(r) for r in rules]
                return result
        except Exception as e:
            logger.error("Policy.get_by_id failed: %s", e)
            return None

    @staticmethod
    def update(policy_id: int, **kwargs) -> bool:
        """更新策略字段."""
        allowed = {"name", "description", "enable_rag", "enable_attack_chain", "tags"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return False
        updates["updated_at"] = datetime.now().isoformat()
        set_clause = ", ".join(f"{k}=?" for k in updates)
        params = list(updates.values()) + [policy_id]
        try:
            with get_connection() as conn:
                conn.execute(f"UPDATE detection_policies SET {set_clause} WHERE id=?", params)
                conn.commit()
                return True
        except Exception as e:
            logger.error("Policy.update failed: %s", e)
            return False

    @staticmethod
    def delete(policy_id: int) -> bool:
        """删除策略."""
        try:
            with get_connection() as conn:
                policy = conn.execute("SELECT is_active FROM detection_policies WHERE id=?", [policy_id]).fetchone()
                if policy and policy["is_active"]:
                    return False  # 激活态不可删除
                conn.execute("DELETE FROM detection_policies WHERE id=?", [policy_id])
                conn.commit()
                return True
        except Exception as e:
            logger.error("Policy.delete failed: %s", e)
            return False

    @staticmethod
    def activate(policy_id: int) -> bool:
        """激活策略（自动反激活其他）. """
        try:
            with get_connection() as conn:
                conn.execute("UPDATE detection_policies SET is_active=0 WHERE is_active=1")
                conn.execute("UPDATE detection_policies SET is_active=1, updated_at=? WHERE id=?",
                             [datetime.now().isoformat(), policy_id])
                conn.commit()
                return True
        except Exception as e:
            logger.error("Policy.activate failed: %s", e)
            return False

    @staticmethod
    def deactivate(policy_id: int) -> bool:
        """停用策略."""
        try:
            with get_connection() as conn:
                conn.execute("UPDATE detection_policies SET is_active=0, updated_at=? WHERE id=?",
                             [datetime.now().isoformat(), policy_id])
                conn.commit()
                return True
        except Exception as e:
            logger.error("Policy.deactivate failed: %s", e)
            return False

    @staticmethod
    def duplicate(policy_id: int) -> Optional[int]:
        """复制派生策略. """
        try:
            original = DetectionPolicy.get_by_id(policy_id)
            if not original:
                return None
            new_id = DetectionPolicy.create(
                name=original["name"] + " (副本)",
                description=original.get("description", ""),
                enable_rag=original.get("enable_rag", 0),
                enable_attack_chain=original.get("enable_attack_chain", 0),
                tags=original.get("tags", ""),
                parent_id=policy_id,
            )
            if new_id is None:
                return None
            # 复制规则
            DetectionPolicy.set_rules(new_id, [r["id"] for r in (original.get("rules") or [])])
            return new_id
        except Exception as e:
            logger.error("Policy.duplicate failed: %s", e)
            return None

    @staticmethod
    def set_rules(policy_id: int, rule_ids: list[int]) -> bool:
        """批量设置策略规则（全量替换）. """
        try:
            with get_connection() as conn:
                conn.execute("DELETE FROM policy_rules WHERE policy_id=?", [policy_id])
                for rid in rule_ids:
                    conn.execute("INSERT OR IGNORE INTO policy_rules (policy_id, rule_id) VALUES (?, ?)",
                                 [policy_id, rid])
                conn.execute("UPDATE detection_policies SET rule_count=?, updated_at=? WHERE id=?",
                             [len(rule_ids), datetime.now().isoformat(), policy_id])
                conn.commit()
                return True
        except Exception as e:
            logger.error("Policy.set_rules failed: %s", e)
            return False

    @staticmethod
    def get_active() -> Optional[dict]:
        """获取当前激活策略（含规则列表）. """
        try:
            with get_connection() as conn:
                row = conn.execute(
                    "SELECT * FROM detection_policies WHERE is_active=1 LIMIT 1"
                ).fetchone()
                if not row:
                    return None
                result = dict(row)
                rules = conn.execute(
                    "SELECT r.id FROM rules r JOIN policy_rules pr ON pr.rule_id=r.id WHERE pr.policy_id=?",
                    [result["id"]]
                ).fetchall()
                result["rule_ids"] = [r["id"] for r in rules]
                return result
        except Exception as e:
            logger.error("Policy.get_active failed: %s", e)
            return None
