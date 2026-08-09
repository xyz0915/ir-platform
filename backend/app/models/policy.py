"""检测策略模型 (DetectionPolicy)."""

import json
import logging
from datetime import datetime
from typing import Optional

from app.database import get_connection
from app.models.rule import Rule

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
                rule_list = [dict(r) for r in rules]
                # 本策略详情：effective = enabled AND (本策略是否激活)
                is_active = bool(result.get("is_active"))
                Rule.annotate_effective(rule_list, {r["id"] for r in rule_list}, is_active)
                result["rules"] = rule_list
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
        """激活策略 = 受控「部署事务」.

        1) 反激活其他策略，本策略 is_active=1；
        2) 以本策略选中集为准对账 rules.enabled（选中→1，未选→0，
           deprecated 规则不改动，安全护栏）；
        3) 对每条被改写的规则写 rule_audit_log，含变更前后 effective_active。
        """
        try:
            from app.models.rule import Rule
            with get_connection() as conn:
                # 部署前：记录原激活策略，用于计算 effective_active 之前态
                prev = conn.execute(
                    "SELECT id FROM detection_policies WHERE is_active=1 LIMIT 1"
                ).fetchone()
                prev_ids: set[int] = set()
                if prev:
                    prev_ids = {
                        r["rule_id"] for r in conn.execute(
                            "SELECT rule_id FROM policy_rules WHERE policy_id=?", [prev["id"]]
                        ).fetchall()
                    }
                # 本策略选中集
                selected = {
                    r["rule_id"] for r in conn.execute(
                        "SELECT rule_id FROM policy_rules WHERE policy_id=?", [policy_id]
                    ).fetchall()
                }
                # 反激活其他 + 激活本策略
                conn.execute("UPDATE detection_policies SET is_active=0 WHERE is_active=1")
                conn.execute(
                    "UPDATE detection_policies SET is_active=1, updated_at=? WHERE id=?",
                    [datetime.now().isoformat(), policy_id],
                )
                conn.commit()

            # 对账写入 rules.enabled（部署）
            all_rules = Rule.list()
            before_active = bool(prev)
            changed = 0
            for r in all_rules:
                rid = r["id"]
                status = r.get("status", "active")
                if status == "deprecated":
                    continue  # 安全护栏：deprecated 永不被部署改写
                should_enable = rid in selected
                currently = bool(r.get("enabled"))
                if should_enable == currently:
                    continue
                # 计算 effective_active 前后态
                eff_before = Rule.effective_active_of(r, prev_ids, before_active)[0]
                eff_after = should_enable  # 部署后：policy_active=True, in_active_policy=should_enable
                try:
                    with get_connection() as wconn:
                        wconn.execute(
                            "UPDATE rules SET enabled=?, version=version+1, updated_at=datetime('now') WHERE id=?",
                            (1 if should_enable else 0, rid),
                        )
                except Exception as wexc:  # noqa: BLE001
                    logger.warning("部署写 enabled 失败 rule=%s: %s", rid, wexc)
                    continue
                Rule._write_audit(
                    rid, "policy_deploy", f"policy#{policy_id}",
                    old_val=json.dumps({"effective_active": eff_before}, ensure_ascii=False, default=str),
                    new_val=json.dumps(
                        {"effective_active": eff_after, "enabled": should_enable, "policy_id": policy_id},
                        ensure_ascii=False, default=str,
                    ),
                )
                changed += 1
            logger.info("Policy %d 部署完成: 改写 %d 条 enabled（选中 %d）", policy_id, changed, len(selected))
            return True
        except Exception as e:  # noqa: BLE001
            logger.error("Policy.activate failed: %s", e)
            return False

    @staticmethod
    def get_active_rule_ids() -> set[int]:
        """返回当前激活策略选中规则 id 集合；无激活策略返回空集合."""
        try:
            with get_connection() as conn:
                row = conn.execute(
                    "SELECT id FROM detection_policies WHERE is_active=1 LIMIT 1"
                ).fetchone()
                if not row:
                    return set()
                ids = conn.execute(
                    "SELECT rule_id FROM policy_rules WHERE policy_id=?", [row["id"]]
                ).fetchall()
                return {r["rule_id"] for r in ids}
        except Exception as e:  # noqa: BLE001
            logger.error("Policy.get_active_rule_ids failed: %s", e)
            return set()

    @staticmethod
    def ensure_active_policy() -> Optional[dict]:
        """保证恰好一个激活策略.

        已存在激活策略 → 直接返回（不做部署，保留手工 override）。
        不存在 → 自动激活基线（默认策略 / id 最小），并告警。
        """
        active = DetectionPolicy.get_active()
        if active:
            return active
        try:
            policies = DetectionPolicy.get_all()
            baseline = next(
                (p for p in policies if "默认" in p.get("name", "") and "副本" not in p.get("name", "")),
                None,
            )
            if not baseline and policies:
                baseline = min(policies, key=lambda p: p["id"])
            if baseline:
                DetectionPolicy.activate(baseline["id"])
                logger.warning(
                    "ensure_active_policy: 无激活策略，已自动激活基线策略 '%s'(id=%d)",
                    baseline.get("name"), baseline["id"],
                )
                return DetectionPolicy.get_active()
        except Exception as e:  # noqa: BLE001
            logger.error("ensure_active_policy failed: %s", e)
        return None

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
