"""合规门禁（Guardrail）Agent — F8 护栏门禁节点（P1-4）。

实现「记录 + 默认放行，显式 block 才阻断」语义：
- 无 ``block`` 标志 → 所有检查项 ``passed=True``，仅记录；
- ``block=true`` → 检查项 ``passed=False``，返回 ``status="blocked"``，
  由引擎将 stage 标记为 failed，阻断下游节点。

引擎 ``PipelineEngine._run_guardrail`` 委托本类，便于独立单测。
"""

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class GuardrailAgent:
    """合规门禁 Agent：评估 ``input_params`` 中的检查规则与阻断标志。"""

    DEFAULT_CHECKS = [{"rule": "default_policy", "action": "record"}]

    def evaluate(self, input_params: Optional[dict]) -> dict:
        """评估门禁规则。

        Args:
            input_params: 含以下可选字段——
                ``checks``: 规则列表，形如 ``[{"rule": str, "detail": str, ...}]``；
                ``block``: bool，显式阻断（默认 False 放行）；
                ``policy``: str，策略名（默认 ``"default"``）；
                ``reason``: str，阻断原因（block 时写入输出）。

        Returns:
            与节点执行体同构的 dict：
            ``{stage, output, confidence, evidence, structured, status}``。
            阻断时 ``status="blocked"``、``confidence=0.0``。
        """
        input_params = input_params or {}
        raw_checks = input_params.get("checks") or self.DEFAULT_CHECKS
        blocked = bool(input_params.get("block"))
        checks = []
        for rule in raw_checks:
            rule_dict = rule if isinstance(rule, dict) else {}
            checks.append({
                "rule": rule_dict.get("rule") or "default_policy",
                "passed": not blocked,
                "detail": rule_dict.get("detail", ""),
            })
        output = "# 合规门禁（Guardrail）\n" + (
            "已阻断：" + str(input_params.get("reason")) if blocked else "校验通过，已记录。"
        )
        return {
            "stage": "guardrail",
            "output": output,
            "confidence": 1.0 if not blocked else 0.0,
            "evidence": [{"type": "guardrail_check", "checks": checks}],
            "structured": {
                "blocked": blocked,
                "checks": checks,
                "policy": input_params.get("policy", "default"),
            },
            "status": "blocked" if blocked else "success",
        }
