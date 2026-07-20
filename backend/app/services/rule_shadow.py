"""影子运行服务（P0-B）.

对候选规则草稿执行影子运行：在历史归一化日志上评估规则，**仅**累计命中次数
（``shadow_hit_count``），**绝不**产生告警。

实现要点：
- 影子规则以 ``is_shadow=True`` 标记交给 :class:`RuleEngine` 评估；引擎在影子分支
  下只计数、不生成告警（详见 ``rules/rule_engine.py``）。
- 草稿同时镜像为 ``rules`` 表中 ``is_shadow=1, enabled=0`` 的行，供引擎批量统计列
  更新，并满足设计文档「rules is_shadow=1」的契约。
"""

import json
import logging
from typing import Any, Dict, List, Optional

from app.database import get_connection
from app.models.rule_draft import RuleDraft
from app.rules.rule_engine import RuleEngine

logger = logging.getLogger(__name__)

# 影子运行单次最多扫描的日志条数（防止性能爆炸）
MAX_SHADOW_LOGS = 5000


class RuleShadow:
    """影子运行执行器."""

    @staticmethod
    def load_sample_logs(
        ids: Optional[List[int]] = None, limit: int = MAX_SHADOW_LOGS
    ) -> List[Dict[str, Any]]:
        """加载归一化日志样本（按 ID 指定或最近 N 条）."""
        with get_connection() as conn:
            if ids:
                placeholders = ",".join("?" for _ in ids) or "?"
                rows = conn.execute(
                    f"SELECT * FROM normalized_logs WHERE id IN ({placeholders})", ids
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM normalized_logs ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def run_shadow(draft_id: int) -> Dict[str, Any]:
        """对指定草稿执行一次影子运行，返回统计.

        Raises:
            ValueError: 草稿不存在时抛出.
        """
        draft = RuleDraft.get_by_id(draft_id)
        if not draft:
            raise ValueError(f"草稿不存在: {draft_id}")

        condition = draft.get("condition") or {}

        # 1) 镜像到 rules（确保影子规则行存在：is_shadow=1, enabled=0）
        RuleShadow._mirror_to_rules(draft, hit_count=None)

        # 2) 构造影子规则（is_shadow 标记，引擎据此只计数不告警）
        shadow_rule: Dict[str, Any] = {
            "name": draft["name"],
            "rule_type": draft.get("rule_type") or "list",
            "condition": condition,
            "severity": draft.get("severity", "medium"),
            "is_shadow": True,
            "shadow_hit_count": 0,
            "_shadow_sample_hits": [],
        }
        logs = RuleShadow.load_sample_logs()
        try:
            RuleEngine.evaluate(logs, [shadow_rule])
        except Exception as exc:  # noqa: BLE001
            logger.warning("影子运行评估异常（降级跳过）: %s", exc)

        hit_count = int(shadow_rule.get("shadow_hit_count", 0))
        sample_hits = list(shadow_rule.get("_shadow_sample_hits", []))[:20]

        # 3) 写回草稿 + rules 计数（_update_rule_stats 已在 evaluate 内更新 rules）
        RuleDraft.update(
            draft_id,
            status=RuleDraft.STATUS_SHADOW,
            shadow_hit_count=hit_count,
            sample_hits=sample_hits,
        )
        RuleShadow._mirror_to_rules(draft, hit_count=hit_count)
        return {
            "draft_id": draft_id,
            "hit_count": hit_count,
            "sample_hits": sample_hits,
            "scanned_logs": len(logs),
        }

    @staticmethod
    def _mirror_to_rules(
        draft: Dict[str, Any], hit_count: Optional[int] = None
    ) -> None:
        """将草稿镜像为 rules 表中的影子规则（is_shadow=1, enabled=0）."""
        name = draft["name"]
        condition = draft.get("condition") or {}
        with get_connection() as conn:
            existing = conn.execute(
                "SELECT id FROM rules WHERE name = ?", (name,)
            ).fetchone()
            if existing:
                if hit_count is None:
                    conn.execute(
                        "UPDATE rules SET is_shadow = 1, enabled = 0, "
                        "updated_at = datetime('now') WHERE name = ?",
                        (name,),
                    )
                else:
                    conn.execute(
                        "UPDATE rules SET is_shadow = 1, enabled = 0, "
                        "shadow_hit_count = ?, updated_at = datetime('now') WHERE name = ?",
                        (hit_count, name),
                    )
            else:
                conn.execute(
                    """
                    INSERT INTO rules
                        (name, description, category, rule_type, condition, severity,
                         enabled, label, source, is_shadow, shadow_hit_count)
                    VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, 1, ?)
                    """,
                    (
                        name,
                        draft.get("rationale"),
                        draft.get("category"),
                        draft.get("rule_type"),
                        json.dumps(condition, ensure_ascii=False),
                        draft.get("severity", "medium"),
                        draft.get("label"),
                        draft.get("source", "ai"),
                        hit_count or 0,
                    ),
                )
