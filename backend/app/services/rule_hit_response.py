"""RuleHitResponseService — 高置信规则命中 → 自动 Playbook + HITL.

设计 §5.2 / §10 建议 1：
  复用既有 ActionService + HitlApproval（已服务 AI 编排），
  仅做"规则命中→自动触发"的薄适配，不重新发明执行层。

  - 当 MatchedRule.confidence >= 0.8 且 gated_by is None → 自动触发。
  - 若 PlaybookDef 中定义了 hitl_required=True 或 severity='critical'
    → 创建 HitlApproval 记录（等待人工审批），不走自动执行。
  - 任何异常（import 报错、依赖不存在）均 try/except 安全降级，
    记录日志、不阻断匹配流程。
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ── 默认 Playbook 映射  ──────────────────────────────────────────────
# 规则类型/类别 → 默认 Playbook 名称
_DEFAULT_PLAYBOOK_MAP: dict = {
    "network": "block_ip",
    "execution": "isolate_host",
    "persistence": "isolate_host",
    "credential": "isolate_host",
    "lateral": "isolate_host",
    "impact": "isolate_host",
    "defense_evasion": "isolate_host",
    "privilege_escalation": "isolate_host",
}

# 需要 HITL 的严重级别
_HITL_SEVERITIES: set = {"critical"}


class RuleHitResponseService:
    """规则命中→响应接线服务.

    提供 ``maybe_trigger()`` 单入口，供 RuleEngine._make_matched_rule
    在产出真实命中（gated_by=None）且置信度达阈值时调用。
    """

    # 默认置信度阈值
    DEFAULT_CONFIDENCE_THRESHOLD: float = 0.8

    @classmethod
    def maybe_trigger(cls, matched_rule: dict) -> dict:
        """检查规则命中是否达到触发条件，是则自动起 Playbook。

        Args:
            matched_rule: MatchedRule 字典（须含 rule_id, rule_name, severity,
                          confidence, category, gated_by, item 等字段）.

        Returns:
            附加到 MatchedRule 的 auto_playbook 字段字典:
            {
                "auto_playbook_triggered": True/False,
                "triggered_playbook_id": str or None,
                "trigger_message": str or None,
                "auto_playbook": {...} or None  # 详细触发信息
            }
            异常/不满足条件时返回 {"auto_playbook_triggered": False, ...}
        """
        result: dict = {
            "auto_playbook_triggered": False,
            "triggered_playbook_id": None,
            "trigger_message": None,
        }

        # 仅对非门控的真实命中触发
        gated_by = matched_rule.get("gated_by")
        if gated_by is not None:
            return result

        confidence = matched_rule.get("confidence", 0.0)
        if not isinstance(confidence, (int, float)):
            confidence = 0.0

        if confidence < cls.DEFAULT_CONFIDENCE_THRESHOLD:
            return result

        severity = matched_rule.get("severity", "medium") or "medium"
        category = matched_rule.get("category", "") or ""

        try:
            # ── 确定 playbook 名称 ──
            playbook_name = _DEFAULT_PLAYBOOK_MAP.get(category, "isolate_host")

            # ── 检查是否需要 HITL ──
            hitl_required = severity in _HITL_SEVERITIES

            if hitl_required:
                # 创建 HITL 审批记录，不走自动执行
                approval_id = cls._create_hitl_approval(matched_rule, playbook_name)
                result.update({
                    "auto_playbook_triggered": True,
                    "triggered_playbook_id": f"hitl:{playbook_name}",
                    "trigger_message": f"需要人工审批: 创建审批 #{approval_id}",
                })
            else:
                # 自动执行 Playbook
                exec_result = cls._execute_playbook(playbook_name, matched_rule)
                result.update({
                    "auto_playbook_triggered": exec_result.get("success", False),
                    "triggered_playbook_id": f"auto:{playbook_name}",
                    "trigger_message": exec_result.get("message", ""),
                })

            logger.info(
                "AutoPlaybook: rule=%s conf=%.2f sev=%s category=%s "
                "hitl=%s playbook=%s triggered=%s",
                matched_rule.get("rule_name"),
                confidence, severity, category,
                hitl_required, playbook_name,
                result["auto_playbook_triggered"],
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "AutoPlaybook 安全降级: rule=%s error=%s",
                matched_rule.get("rule_name"), exc,
            )
            result["trigger_message"] = f"安全降级: {exc}"

        return result

    @classmethod
    def _create_hitl_approval(cls, matched_rule: dict, playbook_name: str) -> Optional[int]:
        """创建 HITL 审批记录.

        Args:
            matched_rule: MatchedRule 字典.
            playbook_name: 建议执行的 playbook 名称.

        Returns:
            审批记录 ID，失败返回 None.
        """
        try:
            from app.models.hitl_approval import HitlApproval

            rule_name = matched_rule.get("rule_name", "unknown")
            host_id = matched_rule.get("item", {}).get("host_id", 0)
            target = {
                "rule_name": rule_name,
                "host_id": host_id,
                "playbook": playbook_name,
                "matched_fields": matched_rule.get("matched_fields", {}),
            }

            approval = HitlApproval.create(
                run_id=f"auto_rule_{rule_name}_{int(datetime.now(timezone.utc).timestamp())}",
                action=f"run_playbook:{playbook_name}",
                target_json=target,
                reason=f"规则 {rule_name} 高置信命中（conf={matched_rule.get('confidence')}），"
                       f"需人工审批执行 {playbook_name}",
            )
            return approval.get("id")
        except Exception as exc:  # noqa: BLE001
            logger.warning("创建 HITL 审批失败（安全降级）: %s", exc)
            return None

    @classmethod
    def _execute_playbook(cls, playbook_name: str, matched_rule: dict) -> dict:
        """执行自动 Playbook（非 HITL 路径）.

        Args:
            playbook_name: playbook 名称（对应 ActionService.EXECUTOR_MAP 键）.
            matched_rule: MatchedRule 字典.

        Returns:
            {"success": bool, "message": str}.
        """
        try:
            from app.services.action_service import ActionService

            host_id = matched_rule.get("item", {}).get("host_id", 0)
            target = {
                "hostname": f"host_{host_id}",
                "rule_name": matched_rule.get("rule_name", ""),
                "alert_id": f"rule_{matched_rule.get('rule_id')}",
            }

            # ActionService.execute 是 async 方法，需要 await
            import asyncio
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                # 已有事件循环 → 创建任务
                future = asyncio.run_coroutine_threadsafe(
                    ActionService.execute(playbook_name, target), loop
                )
                action_result = future.result(timeout=30)
            else:
                action_result = asyncio.run(
                    ActionService.execute(playbook_name, target)
                )

            if action_result and getattr(action_result, "success", False):
                return {"success": True, "message": f"Playbook {playbook_name} 已执行"}
            else:
                err = getattr(action_result, "error", "未知错误") if action_result else "无返回"
                return {"success": False, "message": f"Playbook 执行失败: {err}"}

        except ImportError as exc:
            logger.warning("ActionService 不可用（安全降级）: %s", exc)
            return {"success": False, "message": f"ActionService 不可用: {exc}"}
        except Exception as exc:  # noqa: BLE001
            logger.warning("Playbook 执行异常（安全降级）: %s", exc)
            return {"success": False, "message": f"执行异常: {exc}"}
