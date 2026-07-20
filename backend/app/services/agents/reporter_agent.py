"""报告智能体（ReporterAgent）— P0-A 多智能体闭环（§4.3 / T-A1）.

职责：
- 汇聚分诊 / 调查 / 处置（含 HITL 决议）记录 → 生成结构化复盘报告。
- 沉淀案例经验：写 cases 表持久化 + 调用 KnowledgeRetriever.rebuild_seed_index() 刷新 RAG。
  （完整 RAG 入库经 KnowledgeDraft 审批流在批次 H 落地，本批先做案例持久化 + 索引刷新）

降级要求：AgentLLM 返回 degraded=True 时，仍基于各阶段真实步骤记录产出报告。
"""

import json
import logging
from typing import Any, Optional

from app.database import get_connection
from app.services.agent_llm import AgentLLM
from app.services.agents.base_agent import BaseAgent, AgentResult
from app.services.agents import prompts
from app.services.agents.data_provider import _json_loads

logger = logging.getLogger(__name__)


class ReporterAgent(BaseAgent):
    """报告智能体：汇总闭环结果并沉淀案例。"""

    name = "reporter_agent"
    role = "安全事件复盘报告"
    requires_hitl = False
    confidence_threshold = 0.7

    def __init__(self) -> None:
        super().__init__()
        self._llm = AgentLLM()

    async def run(self, ctx: dict, task: dict) -> AgentResult:
        """生成复盘报告并沉淀案例。"""
        run_id = task.get("run_id") or ctx.get("run_id")
        hitl_decision = task.get("hitl_decision") or {}

        # 从 agent_run_steps 读取各阶段真实输出（鲁棒，跨请求可用）
        triage_out, invest_out, resp_out = self._collect_stage_outputs(run_id, ctx)
        hitl_text = self._format_hitl(hitl_decision)

        report = self._build_report(triage_out, invest_out, resp_out, hitl_text)
        llm_unavailable = False
        try:
            resp = await self._llm.call(
                prompts.build_reporter_prompt(
                    triage_result=triage_out,
                    investigation_result=invest_out,
                    response_result=resp_out,
                    hitl_decision=hitl_text,
                ),
                user=ctx.get("user"),
            )
            if resp.get("degraded") or not resp.get("content"):
                llm_unavailable = True
            else:
                report = resp["content"]
        except Exception as exc:  # noqa: BLE001
            logger.warning("ReporterAgent LLM 调用异常（降级）: %s", exc)
            llm_unavailable = True

        if llm_unavailable:
            report = (
                f"{report}\n\n"
                "[LLM 摘要不可用：以上报告由分诊/调查/处置各阶段真实步骤记录汇总生成]"
            )

        # 沉淀案例（cases 持久化 + RAG 索引刷新）
        try:
            self._sink_case(run_id, report, ctx)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ReporterAgent 案例沉淀失败（不影响报告）: %s", exc)

        # 聚合证据
        evidence = self._collect_evidence(run_id, ctx)

        # 置信度：各阶段平均
        confidences = self._collect_confidences(run_id, ctx)
        confidence = round(sum(confidences) / len(confidences), 2) if confidences else 0.8

        result = AgentResult(
            stage="report",
            output=report,
            confidence=confidence,
            evidence=evidence,
        )
        return result

    # ── 阶段输出收集（DB 优先，ctx 兜底）──
    def _collect_stage_outputs(self, run_id: Optional[str], ctx: dict) -> tuple[str, str, str]:
        """从 agent_run_steps 读取各阶段输出文本。"""
        def _from_ctx(stage: str) -> str:
            return (ctx.get(stage, {}) or {}).get("summary", "") or (ctx.get(stage, {}) or {}).get("output", "")

        if run_id:
            try:
                from app.models.agent_run import AgentRunStep
                steps = AgentRunStep.list_by_run(run_id)
                by_stage = {}
                for s in steps:
                    out = _json_loads(s.get("output_json"), {})
                    by_stage.setdefault(s.get("stage"), out.get("output", ""))
                return (
                    by_stage.get("triage", _from_ctx("triage")),
                    by_stage.get("investigation", _from_ctx("investigation")),
                    by_stage.get("response", _from_ctx("response")),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("ReporterAgent 读取 steps 失败（回退 ctx）: %s", exc)
        return _from_ctx("triage"), _from_ctx("investigation"), _from_ctx("response")

    def _collect_evidence(self, run_id: Optional[str], ctx: dict) -> list[dict]:
        """聚合各阶段证据。"""
        ev: list[dict] = []
        for stage in ("triage", "investigation", "response"):
            s = ctx.get(stage, {}) or {}
            if isinstance(s, dict) and s.get("evidence"):
                ev.extend(s["evidence"])
        if run_id:
            try:
                from app.models.agent_run import AgentRunStep
                for s in AgentRunStep.list_by_run(run_id):
                    e = _json_loads(s.get("evidence_json"), [])
                    if isinstance(e, list):
                        ev.extend(e)
            except Exception:  # noqa: BLE001
                pass
        # 去重
        seen = set()
        uniq = []
        for item in ev:
            key = item.get("ref") or json.dumps(item, sort_keys=True)
            if key not in seen:
                seen.add(key)
                uniq.append(item)
        return uniq[:50]

    def _collect_confidences(self, run_id: Optional[str], ctx: dict) -> list[float]:
        """收集各阶段置信度。"""
        confs: list[float] = []
        for stage in ("triage", "investigation", "response"):
            s = ctx.get(stage, {}) or {}
            if isinstance(s, dict) and isinstance(s.get("confidence"), (int, float)):
                confs.append(float(s["confidence"]))
        if run_id:
            try:
                from app.models.agent_run import AgentRunStep
                for s in AgentRunStep.list_by_run(run_id):
                    c = s.get("confidence")
                    if isinstance(c, (int, float)):
                        confs.append(float(c))
            except Exception:  # noqa: BLE001
                pass
        return confs or [0.8]

    # ── 报告构造 ──
    @staticmethod
    def _build_report(triage_out: str, invest_out: str, resp_out: str, hitl_text: str) -> str:
        """构造数据驱动的复盘报告（Markdown）。"""
        sections = [
            "# 安全事件复盘报告（多智能体闭环）",
            "## 1. 事件概述（分诊）",
            triage_out or "（无分诊记录）",
            "## 2. 调查与根因",
            invest_out or "（无调查记录）",
            "## 3. 处置建议与 HITL 决议",
            resp_out or "（无处置记录）",
            "## 4. HITL 审批",
            hitl_text or "（未触发 HITL 审批）",
            "## 5. 后续加固建议",
            "1. 复盘根因假设，修补对应暴露面；",
            "2. 将本次处置经验沉淀为案例，持续丰富 RAG 知识库；",
            "3. 对同类检测规则命中加强监控。",
        ]
        return "\n\n".join(sections)

    @staticmethod
    def _format_hitl(hitl_decision: dict) -> str:
        """格式化 HITL 决议文本。"""
        if not hitl_decision:
            return "（本批次未触发需审批动作 / 已自动收尾）"
        status = hitl_decision.get("status", "unknown")
        action = hitl_decision.get("action", "")
        decided_by = hitl_decision.get("decided_by", "")
        reason = hitl_decision.get("reason", "")
        executed = hitl_decision.get("executed", {})
        if status == "approved":
            return (
                f"状态：已批准（approve）\n动作：{action}\n审批人：{decided_by}\n"
                f"执行结果：{json.dumps(executed, ensure_ascii=False) if executed else '已执行'}"
            )
        if status == "rejected":
            return f"状态：已拒绝（reject）\n动作：{action}\n审批人：{decided_by}\n原因：{reason}"
        return f"状态：{status}\n动作：{action}"

    # ── 案例沉淀 ──
    @staticmethod
    def _sink_case(run_id: Optional[str], report: str, ctx: dict) -> None:
        """将复盘报告持久化到 cases 表，并刷新 RAG 索引。"""
        name = f"智能体处置案例-{run_id or 'unknown'}"
        try:
            with get_connection() as conn:
                conn.execute(
                    "INSERT INTO cases (name, description, status, created_at, updated_at) "
                    "VALUES (?, ?, 'closed', datetime('now'), datetime('now'))",
                    (name, report[:4000]),
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("写 cases 表失败: %s", exc)

        # 刷新 RAG 索引（chroma 不可用时自动降级，不阻断）
        try:
            from app.services.knowledge_retriever import KnowledgeRetriever
            KnowledgeRetriever.rebuild_seed_index()
        except Exception as exc:  # noqa: BLE001
            logger.debug("RAG 索引刷新跳过: %s", exc)
