"""规则自动调优器（P0-B）.

基于影子运行结果与误报反馈，调用 :class:`AgentLLM` 精炼规则（收紧 DSL / 降低阈值 /
降低严重度），并保留完整调优历史（``tuning_history``）。

人审闭环：
- 调优**不会**直接修改原草稿，而是生成一条新版本草稿（``tuned_version+1``，
  ``parent_draft_id`` 指向原草稿）。
- 原草稿标记为 ``pending_review``，等待管理员在 ``/drafts/{id}/enable`` 审批启用。

若 LLM 不可用，执行启发式降级（移除误报值 / 降低严重度），同样保留历史。
"""

import json
import logging
from typing import Any, Dict, List, Optional

from app.models.rule_draft import RuleDraft
from app.services.agent_llm import AgentLLM
from app.services.rule_dsl import RuleDSL

logger = logging.getLogger(__name__)


class RuleTuner:
    """规则自动调优器."""

    def __init__(self, llm: Optional[AgentLLM] = None):
        self._llm = llm or AgentLLM()

    async def tune(
        self,
        draft: Dict[str, Any],
        false_positive_examples: Optional[List[Dict[str, Any]]] = None,
        feedback: Optional[str] = None,
        user: Optional[dict] = None,
    ) -> Dict[str, Any]:
        """对草稿执行一次调优，返回调优后的新版本草稿（不直接替换原草稿）."""
        prompt = self._build_prompt(draft, false_positive_examples, feedback)
        result = await self._llm.call(prompt, user=user)
        if result.get("error") or result.get("degraded"):
            logger.info("LLM 不可用（%s），回退启发式调优", result.get("error"))
            tuned = self._heuristic_tune(draft, false_positive_examples)
        else:
            tuned = self._parse_llm_response(
                result.get("content", ""), draft, false_positive_examples
            )

        # DSL 安全校验（调优后仍可能非法，记录 dsl_error 供人工复核）
        ok, err = RuleDSL.validate(tuned["rule_type"], tuned["condition"])
        tuned["dsl_error"] = None if ok else err

        # 构建调优历史
        history = list(draft.get("tuning_history") or [])
        history.append(
            {
                "from_version": draft.get("tuned_version", 0),
                "false_positive_examples": false_positive_examples or [],
                "feedback": feedback,
                "rationale": tuned.get("rationale"),
                "llm_degraded": bool(result.get("degraded") or result.get("error")),
            }
        )

        new_version = (draft.get("tuned_version") or 0) + 1
        new_name = f"{draft['name']}_v{new_version}"
        new_draft = RuleDraft.create(
            name=new_name,
            rule_type=tuned["rule_type"],
            condition=tuned["condition"],
            category=draft.get("category"),
            severity=tuned.get("severity", draft.get("severity", "medium")),
            label=tuned.get("label", draft.get("label")),
            rationale=tuned.get("rationale"),
            expected_fields=tuned.get("expected_fields"),
            confidence=tuned.get("confidence"),
            source="ai_tuned",
            parent_draft_id=draft.get("id"),
            status=RuleDraft.STATUS_DRAFT,
            tuned_version=new_version,
            tuning_history=history,
        )
        # 原草稿进入待复审
        RuleDraft.update(draft["id"], status=RuleDraft.STATUS_PENDING_REVIEW)
        return new_draft

    # ── 提示词 ───────────────────────────────────────────────────────────
    def _build_prompt(
        self,
        draft: Dict[str, Any],
        false_positive_examples: Optional[List[Dict[str, Any]]],
        feedback: Optional[str],
    ) -> str:
        fp = json.dumps(false_positive_examples or [], ensure_ascii=False, default=str)
        return (
            "你是安全检测规则调优工程师。请基于以下规则与误报反馈，输出精炼后的规则，"
            "目标是降低误报且不遗漏真实威胁。\n"
            "只返回一个 JSON 对象：\n"
            "{\n"
            '  "rule_type": "...",\n'
            '  "condition": { ... },\n'
            '  "severity": "low|medium|high|critical",\n'
            '  "label": "中文展示名",\n'
            '  "rationale": "调优说明",\n'
            '  "expected_fields": [...],\n'
            '  "confidence": 0.0~1.0\n'
            "}\n"
            "约束：condition 只能使用白名单字段，禁止 eval/exec/SQL/DDL，"
            "禁止正则 '.*' 全匹配。\n"
            f"原规则：\n{json.dumps(draft, ensure_ascii=False, default=str)}\n"
            f"误报样本：\n{fp}\n"
            f"分析师反馈：{feedback or '无'}\n"
        )

    def _parse_llm_response(
        self,
        content: str,
        draft: Dict[str, Any],
        false_positive_examples: Optional[List[Dict[str, Any]]],
    ) -> Dict[str, Any]:
        try:
            start = content.find("{")
            end = content.rfind("}")
            if start == -1 or end == -1:
                raise ValueError("no json")
            obj = json.loads(content[start : end + 1])
            condition = obj.get("condition") or draft.get("condition") or {}
            return {
                "rule_type": obj.get("rule_type", draft.get("rule_type", "list")),
                "condition": condition if isinstance(condition, dict) else {},
                "severity": obj.get("severity", draft.get("severity", "medium")),
                "label": obj.get("label", draft.get("label")),
                "rationale": obj.get("rationale", "LLM 调优"),
                "expected_fields": obj.get("expected_fields")
                or draft.get("expected_fields")
                or [],
                "confidence": float(obj.get("confidence", draft.get("confidence", 0.5)) or 0.5),
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("解析调优响应失败，回退启发式: %s", exc)
            return self._heuristic_tune(draft, false_positive_examples)

    # ── 启发式调优 ───────────────────────────────────────────────────────
    def _heuristic_tune(
        self,
        draft: Dict[str, Any],
        false_positive_examples: Optional[List[Dict[str, Any]]],
    ) -> Dict[str, Any]:
        condition = json.loads(json.dumps(draft.get("condition") or {}))
        severity = draft.get("severity", "medium")
        rationale = "启发式调优：基于误报反馈收紧规则。"
        fps = false_positive_examples or []

        if draft.get("rule_type") == "list" and fps:
            bad = {
                fp.get("value") or fp.get("process_name") or fp.get("event_type")
                for fp in fps
            }
            bad.discard(None)
            vals = condition.get("values") or []
            new_vals = [v for v in vals if v not in bad]
            condition["values"] = new_vals
            rationale = f"移除 {len(bad)} 个误报值，剩余 {len(new_vals)} 个。"
        elif fps:
            sev_map = {
                "critical": "high",
                "high": "medium",
                "medium": "low",
                "low": "low",
            }
            severity = sev_map.get(severity, "low")
            rationale = "存在误报反馈，降低严重度以减少噪声。"

        return {
            "rule_type": draft.get("rule_type", "list"),
            "condition": condition,
            "severity": severity,
            "label": draft.get("label"),
            "rationale": rationale,
            "expected_fields": draft.get("expected_fields") or [],
            "confidence": draft.get("confidence", 0.5),
        }
