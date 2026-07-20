"""知识库自进化服务（P2-H 第⑤批 T-H1）.

误报 → 抑制 → RAG 沉淀 闭环：把分析师反馈（尤其误报 / 抑制）消费后，把经验沉淀回既有知识库，
形成"越用越聪明"的自进化闭环。

闭环管线（针对 false_positive / suppress）：
1. 调用既有 ``RuleSuppression.suppress`` 写入抑制记录（自动抑制，符合"抑制可自动"治理约定）。
2. 调用既有 ``KnowledgeDraft.create`` + ``approve`` 生成 **approved** 知识草稿
   （符合设计文档 §9.4 "H 阶段先将处置经验沉淀为 KnowledgeDraft(approved)"）。
3. 触发 ``KnowledgeRetriever.rebuild_seed_index()`` 把新条目索引进向量库（best-effort，失败忽略）。
4. 回写 ``kb_feedback`` 标记 ``applied_to_kb=1`` 并记录 ``suppression_id`` / ``knowledge_draft_id``。

针对 true_positive：仅沉淀知识（验证有效处置范式），不生成抑制。

所有 LLM 调用统一经 :class:`app.services.agent_llm.AgentLLM`，无可用 Profile 或熔断时
自动降级为确定性处理（不抛异常、不影响闭环）。
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from app.database import get_connection
from app.models.kb_feedback import (
    KbFeedback,
    FEEDBACK_TYPE_FALSE_POSITIVE,
    FEEDBACK_TYPE_SUPPRESS,
    FEEDBACK_TYPE_TRUE_POSITIVE,
)
from app.models.rule_suppression import RuleSuppression
from app.services.agent_llm import AgentLLM

logger = logging.getLogger(__name__)

# 抑制默认有效期（天）
SUPPRESS_DURATION_DAYS = 30
# 自进化沉淀知识的分类
DEPOSIT_CATEGORY_FALSE_POSITIVE = "fp_lesson"
DEPOSIT_CATEGORY_TRUE_POSITIVE = "tp_validation"
DEPOSIT_SOURCE = "kb_self_evolve"


class KbSelfEvolve:
    """知识库自进化服务."""

    def __init__(self, llm: Optional[AgentLLM] = None) -> None:
        self._llm = llm or AgentLLM()

    # ── 公共入口 ────────────────────────────────────────────────────────
    async def ingest_feedback(self, payload: Dict[str, Any], user: Optional[dict] = None) -> Dict[str, Any]:
        """提交一条反馈（写入 ``kb_feedback``，不立即处理）.

        Args:
            payload: 反馈载荷（feedback_type / rule_name / host_id / content ...）.
            user: 当前用户字典（来自 ``get_current_user``），用于记录 ``source_user``.

        Returns:
            创建的反馈记录字典.
        """
        feedback_type = payload.get("feedback_type")
        if not feedback_type:
            raise ValueError("feedback_type 必填")
        record = KbFeedback.create(
            feedback_type=feedback_type,
            rule_id=payload.get("rule_id"),
            alert_id=payload.get("alert_id"),
            event_id=payload.get("event_id"),
            rule_name=payload.get("rule_name"),
            host_id=payload.get("host_id"),
            content=payload.get("content"),
            source_user=(user or {}).get("username"),
        )
        return record

    async def process_feedback(self, feedback_id: int, user: Optional[dict] = None) -> Dict[str, Any]:
        """处理单条反馈，把经验沉淀回知识库，返回处理结果.

        Args:
            feedback_id: 反馈 ID.
            user: 当前用户字典（用于 LLM 审计与溯源）.

        Returns:
            处理结果字典（含 applied_to_kb / suppression_id / knowledge_draft_id / entry_ref）.
        """
        fb = KbFeedback.get_by_id(feedback_id)
        if not fb:
            raise ValueError(f"反馈 {feedback_id} 不存在")

        result: Dict[str, Any] = {
            "feedback_id": feedback_id,
            "feedback_type": fb.get("feedback_type"),
            "already_applied": bool(fb.get("applied_to_kb")),
            "applied_to_kb": bool(fb.get("applied_to_kb")),
            "suppression_id": fb.get("suppression_id"),
            "knowledge_draft_id": fb.get("knowledge_draft_id"),
            "entry_ref": fb.get("entry_ref"),
            "summary": fb.get("summary"),
        }
        if fb.get("applied_to_kb"):
            return result

        feedback_type = fb.get("feedback_type")
        suppression_id: Optional[int] = None
        knowledge_draft_id: Optional[int] = None
        entry_ref: Optional[str] = None
        summary: Optional[str] = None

        # 1) 误报 / 抑制 → 先写抑制
        if feedback_type in (FEEDBACK_TYPE_FALSE_POSITIVE, FEEDBACK_TYPE_SUPPRESS):
            suppression_id = self._apply_suppression(fb)

        # 2) 三类反馈均沉淀知识（true_positive 沉淀为有效范式；误报沉淀为规避经验）
        knowledge_draft_id, entry_ref, summary = await self._deposit_knowledge(fb, user)

        # 3) 回写反馈状态
        KbFeedback.mark_applied(
            feedback_id,
            kb_entry_id=entry_ref,
            suppression_id=suppression_id,
            knowledge_draft_id=knowledge_draft_id,
            entry_ref=entry_ref,
            summary=summary,
        )
        result.update(
            {
                "applied_to_kb": True,
                "suppression_id": suppression_id,
                "knowledge_draft_id": knowledge_draft_id,
                "entry_ref": entry_ref,
                "summary": summary,
            }
        )
        return result

    async def evolve_all(self, user: Optional[dict] = None) -> Dict[str, Any]:
        """处理所有尚未沉淀的反馈，返回批量处理结果.

        Args:
            user: 当前用户字典.

        Returns:
            ``{"processed": int, "applied": int, "details": [...]}``.
        """
        pending = KbFeedback.list_unapplied(limit=1000)
        processed = 0
        applied = 0
        details: List[Dict[str, Any]] = []
        for fb in pending:
            try:
                res = await self.process_feedback(fb["id"], user=user)
                processed += 1
                if res.get("applied_to_kb"):
                    applied += 1
                details.append(res)
            except Exception as exc:  # noqa: BLE001
                logger.error("处理反馈 %s 失败: %s", fb["id"], exc)
                details.append({"feedback_id": fb["id"], "error": str(exc)})
        return {"processed": processed, "applied": applied, "details": details}

    def stats(self) -> Dict[str, Any]:
        """返回自进化统计与沉淀条目列表."""
        return KbFeedback.get_stats()

    # ── 内部工具 ────────────────────────────────────────────────────────
    def _apply_suppression(self, fb: Dict[str, Any]) -> Optional[int]:
        """对规则写入抑制（自动，best-effort），返回抑制记录 ID."""
        rule_name = fb.get("rule_name")
        if not rule_name:
            logger.info("反馈 %s 无 rule_name，跳过抑制", fb.get("id"))
            return None
        host_id = int(fb.get("host_id") or 0)
        reason = fb.get("content") or "误报/抑制反馈自动沉淀"
        try:
            RuleSuppression.suppress(
                rule_name=rule_name,
                host_id=host_id,
                duration_days=SUPPRESS_DURATION_DAYS,
                reason=reason,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("写入抑制失败（已忽略）: %s", exc)
            return None
        # 回查抑制记录 ID（RuleSuppression.suppress 仅返回 bool，避免改动既有封装）
        try:
            with get_connection() as conn:
                row = conn.execute(
                    "SELECT id FROM rule_suppression WHERE rule_name=? AND host_id=? "
                    "ORDER BY id DESC LIMIT 1",
                    (rule_name, host_id),
                ).fetchone()
            return row["id"] if row else None
        except Exception:  # noqa: BLE001
            return None

    async def _deposit_knowledge(
        self, fb: Dict[str, Any], user: Optional[dict] = None
    ) -> Tuple[int, str, str]:
        """把反馈沉淀为 approved 知识草稿并重建向量索引，返回 (draft_id, entry_ref, summary)."""
        summary = await self._gen_summary(fb, user)
        title = self._build_title(fb)
        description = fb.get("content") or summary
        rule_name = fb.get("rule_name")
        category = (
            DEPOSIT_CATEGORY_TRUE_POSITIVE
            if fb.get("feedback_type") == FEEDBACK_TYPE_TRUE_POSITIVE
            else DEPOSIT_CATEGORY_FALSE_POSITIVE
        )
        # 延迟导入，避免 chroma / sentence-transformers 在模块加载期被引入（利于测试隔离）
        from app.models.knowledge_draft import KnowledgeDraft

        draft = KnowledgeDraft.create(
            title=title,
            description=description,
            category=category,
            severity="low",
            pattern=rule_name or "",
            source=DEPOSIT_SOURCE,
            raw_ioc=None,
        )
        draft_id = draft["id"]
        # 自进化沉淀：自动审核通过（设计文档 §9.4）
        try:
            KnowledgeDraft.approve(draft_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("知识草稿 %s 自动审批失败（已忽略）: %s", draft_id, exc)

        entry_ref = f"draft_{draft_id}"
        # best-effort 向量索引重建
        try:
            from app.services.knowledge_retriever import KnowledgeRetriever

            KnowledgeRetriever.rebuild_seed_index()
        except Exception as exc:  # noqa: BLE001
            logger.warning("rebuild_seed_index 失败（已忽略，不影响沉淀）: %s", exc)

        return draft_id, entry_ref, summary

    async def _gen_summary(self, fb: Dict[str, Any], user: Optional[dict] = None) -> str:
        """调用 LLM 生成沉淀摘要；不可用或异常时回退确定性摘要."""
        prompt = self._build_summary_prompt(fb)
        try:
            result = await self._llm.call(prompt, user=user)
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM 调用异常，使用确定性摘要: %s", exc)
            return self._deterministic_summary(fb)
        if result.get("degraded") or result.get("error") or not result.get("content"):
            logger.info("LLM 不可用（%s），使用确定性摘要", result.get("error"))
            return self._deterministic_summary(fb)
        content = (result.get("content") or "").strip()
        return content or self._deterministic_summary(fb)

    # ── 提示词与确定性回退 ──────────────────────────────────────────────
    @staticmethod
    def _type_label(feedback_type: Optional[str]) -> str:
        return {
            FEEDBACK_TYPE_FALSE_POSITIVE: "误报",
            FEEDBACK_TYPE_SUPPRESS: "抑制",
            FEEDBACK_TYPE_TRUE_POSITIVE: "真阳性（有效）",
        }.get(feedback_type or "", feedback_type or "反馈")

    def _build_title(self, fb: Dict[str, Any]) -> str:
        rule_name = fb.get("rule_name") or f"事件{fb.get('event_id') or fb.get('id')}"
        return f"自进化经验：{rule_name}（{self._type_label(fb.get('feedback_type'))}）"

    def _build_summary_prompt(self, fb: Dict[str, Any]) -> str:
        return (
            "你是安全运营知识库维护助手。请基于以下分析师反馈，生成一条简洁的中文知识沉淀摘要"
            "（用于写入团队知识库，供后续相似告警的语义检索召回）。\n"
            "要求：1-3 句话，说明该经验是什么、今后如何规避/识别，不要包含敏感 PII。\n"
            f"反馈类型：{self._type_label(fb.get('feedback_type'))}\n"
            f"关联规则：{fb.get('rule_name') or '无'}\n"
            f"分析师备注：{fb.get('content') or '无'}\n"
        )

    @staticmethod
    def _deterministic_summary(fb: Dict[str, Any]) -> str:
        rule_name = fb.get("rule_name") or "该规则/事件"
        ftype = fb.get("feedback_type")
        if ftype == FEEDBACK_TYPE_TRUE_POSITIVE:
            return f"经验沉淀：{rule_name} 被确认为有效告警，该处置范式值得复用。"
        note = fb.get("content") or ""
        return (
            f"经验沉淀：{rule_name} 被标记为{('误报' if ftype == FEEDBACK_TYPE_FALSE_POSITIVE else '需抑制')}"
            f"{('，备注：' + note) if note else ''}；已自动抑制并沉淀为知识，后续相似命中应降低置信度。"
        )
