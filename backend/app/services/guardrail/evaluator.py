"""护栏评估器 — 实现 01-api-spec.md §7.3 算法（§3.2 代码骨架）.

严格对齐方案语义：
  1. 按 action 通配匹配首个 enabled 策略（action_pattern 支持 ``*``）。
  2. 命中策略后：whitelist_hit = whitelist.includes(action)。
  3. requires_confirm = policy.require_confirm；
     requires_rollback_plan = !!policy.rollback_plan。
  4. passed = whitelist_hit OR 非高危(risk not in high/critical) OR 有回滚预案。
  5. 命中（匹配到策略）即记 GuardrailHit；无匹配策略默认放行且不记 Hit。
"""

import json
import logging
from typing import Any, Optional

from app.models.guardrail import GuardrailHit, GuardrailPolicy

logger = logging.getLogger(__name__)


class GuardrailEvaluator:
    """护栏门禁评估器（静态方法，无状态）。"""

    @staticmethod
    def evaluate(action: str, context: Optional[dict] = None) -> dict:
        """评估某动作是否通过护栏门禁。

        Args:
            action: 待执行的动作标识，如 ``host:isolate:web01``。
            context: 运行上下文，可选携带 ``run_id`` 等用于命中记录关联。

        Returns:
            GuardrailResult：
            ``{policy_id, whitelist_hit, requires_confirm,
               requires_rollback_plan, passed}``。
        """
        context = context or {}
        policy = GuardrailPolicy.match_action(action)  # 首个 enabled 且通配命中
        if policy is None:
            # 无策略适用 → 默认放行，不记 Hit
            return {
                "policy_id": None,
                "whitelist_hit": False,
                "requires_confirm": False,
                "requires_rollback_plan": False,
                "passed": True,
            }
        whitelist = json.loads(policy.get("whitelist") or "[]")
        whitelist_hit = action in whitelist
        requires_confirm = bool(policy.get("require_confirm"))
        requires_rollback_plan = bool(policy.get("rollback_plan"))
        risk_high = policy.get("risk_level") in ("high", "critical")
        passed = whitelist_hit or (not risk_high) or requires_rollback_plan
        # 命中即记 GuardrailHit
        GuardrailHit.record(
            policy.get("policy_id"), context.get("run_id"), action, passed
        )
        return {
            "policy_id": policy.get("policy_id"),
            "whitelist_hit": whitelist_hit,
            "requires_confirm": requires_confirm,
            "requires_rollback_plan": requires_rollback_plan,
            "passed": passed,
        }
