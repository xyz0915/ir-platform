"""轻量编排器（状态机）— 自建，无外部依赖（§2.1 / §8）。

本期（第①批）仅提供**骨架 + 数据模型贯通**：
- start_run: 创建一次 agent_run（pending）。
- dispatch: 串行执行单个 Agent，写 agent_run_steps。
- wait_hitl: 阻塞网关，置 run=waiting_hitl 并写 hitl_approvals。
- _state_machine: 根据步骤结果推进 run 状态（running→completed/failed/waiting_hitl）。

真正的多智能体循环（A 批次）将在此基础上扩展并行调度与 HITL 决议回写。
"""

import asyncio
import json
import logging
import uuid
from typing import Any, Optional

from app.models.agent_run import AgentRun, AgentRunStep
from app.models.hitl_approval import HitlApproval
from app.services.agents.base_agent import BaseAgent, AgentResult
from app.services.sse_manager import sse_manager

logger = logging.getLogger(__name__)


class Orchestrator:
    """轻量编排器：按阶段串行/并行调度 BaseAgent 子类，状态机驱动。"""

    # run 状态枚举
    STATUS_PENDING = "pending"
    STATUS_RUNNING = "running"
    STATUS_WAITING_HITL = "waiting_hitl"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"
    STATUS_CANCELLED = "cancelled"

    def __init__(self) -> None:
        pass

    # ── 1. 启动一次运行 ──
    def start_run(
        self,
        event_id: Optional[str] = None,
        case_id: Optional[int] = None,
        title: str = "",
        stage: str = "triage",
        priority: str = "P2",
        user: Optional[dict] = None,
        ctx_json: Optional[str] = None,
    ) -> dict:
        """创建一次 agent_run（初始状态 pending）。

        Args:
            ctx_json: 可选的上下文 JSON 字符串，持久化到 agent_runs.ctx_json。

        Returns:
            新建的 agent_run 行（dict）。
        """
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        run = AgentRun.create(
            run_id=run_id,
            event_id=event_id,
            case_id=case_id,
            title=title or f"Run {run_id}",
            stage=stage,
            status=self.STATUS_PENDING,
            priority=priority,
            user_id=user.get("id") if user else None,
            ctx_json=ctx_json,
        )
        logger.info(
            "Orchestrator.start_run: run_id=%s, event_id=%s", run_id, event_id
        )
        logger.info(
            json.dumps({"event": "run_started", "run_id": run_id, "event_id": event_id or "", "priority": priority, "stage": stage})
        )
        return run

    # ── 2. 派发并执行单个 Agent ──
    async def dispatch(
        self,
        run_id: str,
        agent: BaseAgent,
        ctx: dict,
        task: Optional[dict] = None,
        is_final: bool = False,
    ) -> AgentResult:
        """派发单个 Agent 执行，并写 agent_run_steps。

        流程：
        1. 置 run=running。
        2. 调 agent.run()（内部经 AgentLLM 调用大模型）。
        3. 写一步 agent_run_steps（含审计关联）。
        4. 触发状态机推进 / HITL 阻塞网关。

        Args:
            is_final: 是否为最终阶段；True 时 _state_machine 会标记 run=completed。
        """
        task = task or {}
        run = AgentRun.get_by_run_id(run_id)
        if not run:
            raise ValueError(f"run_id 不存在: {run_id}")

        AgentRun.update(run_id, status=self.STATUS_RUNNING, current_agent=agent.name)

        step_agent = agent.name
        stage = agent._stage() if hasattr(agent, "_stage") else "triage"
        input_json = {"ctx": _safe_json(ctx), "task": _safe_json(task)}
        audit_log_id: Optional[int] = None

        # SSE 推送：步骤开始
        asyncio.ensure_future(sse_manager.push(
            run_id,
            "step_update",
            {
                "type": "step_update",
                "run_id": run_id,
                "step_id": str(step_agent),
                "agent": step_agent,
                "stage": stage,
                "status": "running",
                "output": "",
                "evidence": {"data_sources": [], "evidence": []},
                "elapsed_seconds": 0,
            },
        ))

        try:
            # P0-1.2: Agent.run() 设 120s 超时，避免单 Agent 永久阻塞整条 pipeline
            result = await asyncio.wait_for(agent.run(ctx, task), timeout=120.0)
        except asyncio.TimeoutError:
            logger.warning(
                "Orchestrator dispatch timeout: run_id=%s, agent=%s (120s)", run_id, step_agent
            )
            AgentRun.update(run_id, status=self.STATUS_FAILED)
            AgentRunStep.add(
                run_id=run_id,
                stage=stage,
                agent=step_agent,
                status="failed",
                input_json=input_json,
                output_json={"error": "Agent execution timed out after 120s"},
                confidence=0.0,
                evidence_json=[],
                audit_log_id=audit_log_id,
            )
            asyncio.ensure_future(sse_manager.push(
                run_id,
                "step_update",
                {
                    "type": "step_update",
                    "run_id": run_id,
                    "step_id": str(step_agent),
                    "agent": step_agent,
                    "stage": stage,
                    "status": "failed",
                    "output": "Agent execution timed out after 120s",
                    "evidence": {"data_sources": [], "evidence": []},
                    "elapsed_seconds": 0,
                },
            ))
            self._state_machine(run_id, failed=True)
            return AgentResult(stage=stage, output="", confidence=0.0, hitl=False)
        except asyncio.CancelledError:
            logger.warning(
                "Orchestrator dispatch cancelled: run_id=%s, agent=%s", run_id, step_agent
            )
            AgentRun.update(run_id, status=self.STATUS_CANCELLED)
            raise  # 重新抛出，允许上层清理
        except Exception as exc:  # noqa: BLE001
            logger.exception("Agent %s 执行失败: %s", step_agent, exc)
            AgentRunStep.add(
                run_id=run_id,
                stage=stage,
                agent=step_agent,
                status="failed",
                input_json=input_json,
                output_json={"error": str(exc)},
                confidence=0.0,
                evidence_json=[],
                audit_log_id=audit_log_id,
            )
            # SSE 推送：步骤失败
            asyncio.ensure_future(sse_manager.push(
                run_id,
                "step_update",
                {
                    "type": "step_update",
                    "run_id": run_id,
                    "step_id": str(step_agent),
                    "agent": step_agent,
                    "stage": stage,
                    "status": "failed",
                    "output": str(exc)[:2000],
                    "evidence": {"data_sources": [], "evidence": []},
                    "elapsed_seconds": 0,
                },
            ))
            self._state_machine(run_id, failed=True)
            return AgentResult(stage=stage, output="", confidence=0.0, hitl=False)

        output_json = result.to_dict()
        AgentRunStep.add(
            run_id=run_id,
            stage=stage,
            agent=step_agent,
            status="success",
            input_json=input_json,
            output_json=output_json,
            confidence=result.confidence,
            evidence_json=result.evidence,
            audit_log_id=audit_log_id,
        )

        # SSE 推送：步骤完成 — 构造证据数据
        evidence_payload = {"data_sources": [], "evidence": []}
        if result.evidence:
            for ev in result.evidence:
                if isinstance(ev, dict):
                    source_id = ev.get("ref", ev.get("id", ""))
                    if source_id:
                        evidence_payload["data_sources"].append({
                            "id": source_id,
                            "type": ev.get("type", "action"),
                            "label": ev.get("label", source_id),
                            "properties": {k: v for k, v in ev.items() if k not in ("type", "ref", "id", "label")},
                        })
                    target_ref = ev.get("target_ref")
                    if target_ref:
                        evidence_payload["evidence"].append({
                            "source_id": source_id,
                            "target_id": target_ref,
                            "relation": ev.get("relation", "关联"),
                            "description": ev.get("description", ""),
                        })
        asyncio.ensure_future(sse_manager.push(
            run_id,
            "step_completed",
            {
                "type": "step_completed",
                "run_id": run_id,
                "step_id": str(step_agent),
                "agent": step_agent,
                "stage": stage,
                "status": "completed",
                "output": result.output[:2000] if result.output else "",
                "evidence": evidence_payload,
                "elapsed_seconds": result.execution_duration_ms / 1000.0 if result.execution_duration_ms else 0,
                "summary": result.output[:200] if result.output else "",
            },
        ))

        # P1-4: ctx 持久化 — agent 执行成功后回写 ctx_json
        AgentRun.update(run_id, ctx_json=_safe_json(ctx))

        # HITL 网关：需要人工且未达免审批阈值 → 阻塞
        if getattr(agent, "requires_hitl", False) and result.hitl:
            # 动作目标优先取 task，其次取 Agent 写入 ctx["responder_action"] 的内容
            ra = (ctx or {}).get("responder_action", {}) or {}
            action = task.get("action") or ra.get("action") or "custom"
            target_json = task.get("target_json") or ra.get("target") or {}
            auto_rollback_plan = (
                task.get("auto_rollback_plan") or ra.get("auto_rollback_plan") or {}
            )
            await self.wait_hitl(
                run_id=run_id,
                action=action,
                requested_by=run.get("user_id"),
                target_json=target_json,
                step_id=None,
                auto_rollback_plan=auto_rollback_plan,
                reason=result.output[:500],
            )
            return result

        self._state_machine(run_id, result=result, is_final=is_final)
        logger.info(
            json.dumps({"event": "agent_completed", "run_id": run_id, "agent": step_agent, "stage": stage, "status": "success", "confidence": result.confidence})
        )
        return result

    # ── 3. HITL 阻塞网关 ──
    async def wait_hitl(
        self,
        run_id: str,
        action: str,
        requested_by: Optional[int] = None,
        step_id: Optional[int] = None,
        target_json: Optional[dict] = None,
        auto_rollback_plan: Optional[dict] = None,
        reason: Optional[str] = None,
    ) -> dict:
        """置 run=waiting_hitl 并写一条 pending 的 hitl_approvals。

        同时广播 WebSocket 通知。

        返回新建的审批记录（dict）。真正的决议（approve/reject）由 HITL 接口回写
        （§8.4，后续批次扩展），本期先打通数据模型。
        """
        AgentRun.update(run_id, status=self.STATUS_WAITING_HITL)
        approval = HitlApproval.create(
            run_id=run_id,
            step_id=step_id,
            action=action,
            requested_by=requested_by,
            target_json=target_json or {},
            auto_rollback_plan=auto_rollback_plan or {},
            reason=reason,
        )
        approval_id = approval.get("id")
        logger.info(
            "Orchestrator.wait_hitl: run_id=%s, approval_id=%s, action=%s",
            run_id, approval_id, action,
        )

        # P1-3: HITL 通知
        await self._notify_hitl_pending(run_id, action, approval_id)

        return approval

    # ── 3b. HITL 通知 ──
    async def _notify_hitl_pending(self, run_id: str, action: str, approval_id: int) -> None:
        """广播 HITL 待审批通知（非阻塞，失败仅记录日志）。"""
        try:
            from app.services.notification_service import notify_hitl_pending

            await notify_hitl_pending(run_id=run_id, action=action, approval_id=approval_id)
        except Exception as exc:
            logger.warning("HITL notification failed (non-blocking): %s", exc)

    # ── 4. 状态机推进 ──
    def _state_machine(
        self,
        run_id: str,
        result: Optional[AgentResult] = None,
        failed: bool = False,
        is_final: bool = False,
    ) -> None:
        """根据执行结果推进 agent_run 状态。

        - failed=True → status=failed
        - is_final=True → status=completed
        - is_final=False → 仅更新 stage/confidence/result_json，不修改 status
        - confidence / result_json 回写
        """
        if failed:
            AgentRun.update(run_id, status=self.STATUS_FAILED)
            return

        update_kwargs: dict[str, Any] = {}
        if is_final:
            update_kwargs["status"] = self.STATUS_COMPLETED
        if result is not None:
            update_kwargs["confidence"] = result.confidence
            update_kwargs["result_json"] = _safe_json(result.to_dict())
            if result.stage in ("triage", "investigation", "response", "report"):
                update_kwargs["stage"] = result.stage
        if update_kwargs:
            AgentRun.update(run_id, **update_kwargs)

    # ── 5. 多智能体串行闭环（A 批次扩展）──
    async def run_pipeline(
        self,
        run_id: str,
        user: Optional[dict] = None,
        ctx: Optional[dict] = None,
    ) -> dict:
        """串行驱动 triage → investigation → responder（触发 HITL 网关）→ 等待审批。

        默认零自主：responder 必然触发 HITL 网关，run 进入 waiting_hitl 并暂停，
        待管理员在 /approve 决议后由 ``resume`` 收尾（reporter）。

        Returns:
            ``{"run_id", "status", "stage"}``
        """
        from app.services.agents.triage_agent import TriageAgent
        from app.services.agents.investigator_agent import InvestigatorAgent
        from app.services.agents.responder_agent import ResponderAgent

        ctx = ctx or {}
        ctx["run_id"] = run_id
        ctx["user"] = user or {}
        # P1-5.2: 生成 Trace ID 贯穿整个编排链路
        ctx["trace_id"] = uuid.uuid4().hex[:16]
        logger.info(
            json.dumps({"event": "pipeline_started", "run_id": run_id, "trace_id": ctx["trace_id"]})
        )

        # 1) 分诊 — 非最终阶段
        await self.dispatch(
            run_id,
            TriageAgent(),
            ctx,
            task={"event_id": ctx.get("event_id"), "event_ids": ctx.get("event_ids")},
            is_final=False,
        )
        # 2) 调查（含防御式调用 RootCauseAgent）— 非最终阶段
        await self.dispatch(run_id, InvestigatorAgent(), ctx, task={}, is_final=False)
        # 3) 处置（默认零自主 → 触发 HITL 网关，run 变为 waiting_hitl）— 非最终阶段
        await self.dispatch(run_id, ResponderAgent(), ctx, task={}, is_final=False)

        run = AgentRun.get_by_run_id(run_id)
        if run and run.get("status") == self.STATUS_WAITING_HITL:
            return {
                "run_id": run_id,
                "status": self.STATUS_WAITING_HITL,
                "stage": "response",
            }
        # 极少见（responder 未触发 HITL）：直接收尾
        return await self._finish_with_reporter(run_id, ctx, user, hitl_decision=None)

    async def resume(
        self,
        run_id: str,
        approval: dict,
        decided_by: Optional[int] = None,
        user: Optional[dict] = None,
    ) -> dict:
        """HITL 决议后收尾：执行处置动作 + 写处置记录 + 生成报告.

        模式感知（§1.4.2）：
        - mode=='custom'（默认/自定义 pipeline）：执行 responder 实际动作 + 仅就已有
          reporter 步骤用 hitl_decision 重跑一次 ReporterAgent（更新输出，不新建重复步骤），
          最后置 completed。
        - mode=='hardcoded'（或 ctx 缺失）：行为完全不变，走 ``_finish_with_reporter``。

        Args:
            run_id: 运行 ID。
            approval: 已决议的 hitl_approvals 记录（dict）。
            decided_by: 决议人用户 ID（审批管理员）。
            user: 当前用户字典（用于审计）。

        Returns:
            ``{"run_id", "status", "executed", "result"}``
        """
        from app.services.agents.responder_agent import ResponderAgent

        run = AgentRun.get_by_run_id(run_id)
        event_id = run.get("event_id") if run else None
        operator = (user or {}).get("username") or "admin"

        # 降级路径：auto_rule_* 等无 agent_runs 记录的 run_id，仅落库 status，跳过实际执行
        if not run:
            logger.info(
                "Orchestrator.resume: run_id=%s 无 agent_runs 记录，走降级路径（仅标记状态）",
                run_id,
            )
            status_text = approval.get("status", "unknown")
            return {
                "run_id": run_id,
                "status": status_text,
                "executed": False,
                "result": {
                    "stage": "response",
                    "output": f"run has no agent_runs record; approval marked as {status_text}",
                    "confidence": 1.0,
                    "hitl": False,
                    "evidence": [],
                },
            }

        # P1-4: 从 DB 读取持久化的 ctx_json 重建上下文
        ctx_json_str = run.get("ctx_json") if run else None
        ctx = json.loads(ctx_json_str) if ctx_json_str else {}
        ctx.update({
            "run_id": run_id,
            "event_id": event_id,
            "user": user or {},
        })

        hitl_decision: Optional[dict] = None
        executed: dict = {}
        if approval.get("status") == HitlApproval.STATUS_APPROVED:
            action = approval.get("action") or "export_report"
            try:
                target = json.loads(approval.get("target_json") or "{}")
            except (json.JSONDecodeError, TypeError):
                target = {}
            responder = ResponderAgent()
            executed, rollback = await responder.execute_action(
                action=action, target=target, event_id=event_id, operator=operator
            )
            hitl_decision = {
                "status": "approved",
                "action": action,
                "decided_by": decided_by,
                "executed": executed,
                "rollback": rollback,
            }
        else:
            hitl_decision = {
                "status": "rejected",
                "action": approval.get("action"),
                "decided_by": decided_by,
                "reason": approval.get("reason"),
            }

        # 模式感知收尾（§1.4.2）
        mode = ctx.get("mode", "hardcoded")
        if mode == "custom":
            return await self._resume_custom(run_id, ctx, user, hitl_decision, executed)
        return await self._finish_with_reporter(run_id, ctx, user, hitl_decision, executed)

    async def _resume_custom(
        self,
        run_id: str,
        ctx: dict,
        user: Optional[dict],
        hitl_decision: Optional[dict],
        executed: Optional[dict] = None,
    ) -> dict:
        """custom 模式 resume：仅就已有 reporter 步骤用 hitl_decision 重跑 ReporterAgent 并刷新输出。

        不新建重复 reporter 步骤（§1.4.2 / §8.3）。最后置 run=completed + 推送 run_completed。
        """
        from app.services.agents.reporter_agent import ReporterAgent
        from app.models.agent_run import AgentRunStep

        reporter = ReporterAgent()
        task = {"run_id": run_id, "hitl_decision": hitl_decision or {}}

        # 找到已有 reporter 步骤（agent == 'reporter' 或 stage == 'report'）
        steps = AgentRunStep.list_by_run(run_id)
        reporter_step = next(
            (s for s in steps if s.get("agent") == "reporter" or s.get("stage") == "reporter"),
            None,
        )
        if reporter_step:
            result = await reporter.run(ctx, task)
            AgentRunStep.update(
                reporter_step["id"],
                status="success",
                output_json=result.to_dict(),
                confidence=result.confidence,
                evidence_json=result.evidence,
            )
        else:
            # 兜底：理论不会走到（ensure_reporter 已保证尾部 reporter），无 reporter 步骤则新增
            logger.warning(
                "Orchestrator._resume_custom: run_id=%s 无 reporter 步骤，兜底新增",
                run_id,
            )
            await self.dispatch(run_id, reporter, ctx, task=task, is_final=True)

        AgentRun.update(run_id, status=self.STATUS_COMPLETED, stage="report")
        asyncio.ensure_future(sse_manager.push(
            run_id,
            "run_completed",
            {"type": "run_completed", "run_id": run_id, "status": "completed"},
        ))
        return {
            "run_id": run_id,
            "status": self.STATUS_COMPLETED,
            "executed": executed or {},
            "result": {
                "stage": "report",
                "hitl_decision": hitl_decision,
            },
        }

    # ── 6. 自定义管道执行（PipelineEngine）──
    async def run_custom_pipeline(
        self,
        run_id: str,
        agent_names: list[str],
        event_id: str,
        user: dict,
        use_cache: bool = True,
        ensure_reporter: bool = True,
    ) -> dict:
        """按自定义 Agent 列表执行管道（替代固定 4 阶段）。

        使用 PipelineEngine 替代硬编码 dispatch 调用。
        支持 DAG 拓扑排序、分批并行执行、缓存查询、HITL 暂停。

        默认 ``ensure_reporter=True``：引擎在 agent_names 尾部补 ``"reporter"``，
        保证任何自定义/默认 pipeline 都必定产出真实报告步骤并以 completed 结束
        （对齐硬编码路径 ``_finish_with_reporter`` 语义，§1.4.1）。

        Args:
            run_id: 运行 ID。
            agent_names: 有序 Agent 名称列表（用于 DAG 依赖解析）。
            event_id: 关联安全事件 ID。
            user: 用户信息。
            use_cache: 是否启用缓存。
            ensure_reporter: 是否由引擎在尾部统一追加 reporter 收尾。

        Returns:
            {"run_id", "status", "stages", "total_elapsed", "results"}
        """
        from app.services.agents.pipeline_engine import pipeline_engine

        ctx = {
            "run_id": run_id,
            "event_id": event_id,
            "user": user or {},
            # 标记模式，供 resume 做模式感知（custom 仅刷新 reporter / hardcoded 走 _finish_with_reporter）
            "mode": "custom",
            "agent_names": list(agent_names or []),
        }

        result = await pipeline_engine.run(
            run_id=run_id,
            agent_names=agent_names,
            event_id=event_id,
            ctx=ctx,
            user=user or {},
            use_cache=use_cache,
            ensure_reporter=ensure_reporter,
        )

        # 与硬编码路径对齐：完成时推送 run_completed SSE（引擎本身仅推 pipeline_complete）
        if result.get("status") == self.STATUS_COMPLETED:
            asyncio.ensure_future(sse_manager.push(
                run_id,
                "run_completed",
                {"type": "run_completed", "run_id": run_id, "status": "completed"},
            ))
        return result

    async def _finish_with_reporter(
        self,
        run_id: str,
        ctx: dict,
        user: Optional[dict],
        hitl_decision: Optional[dict],
        executed: Optional[dict] = None,
    ) -> dict:
        """收尾：运行 ReporterAgent 生成报告并标记 run 完成。"""
        from app.services.agents.reporter_agent import ReporterAgent

        reporter = ReporterAgent()
        task = {"run_id": run_id, "hitl_decision": hitl_decision or {}}
        # 最终阶段 — is_final=True 使 _state_machine 标记 completed
        result = await self.dispatch(run_id, reporter, ctx, task=task, is_final=True)
        AgentRun.update(run_id, status=self.STATUS_COMPLETED, stage="report")
        # SSE 推送：运行完成
        asyncio.ensure_future(sse_manager.push(
            run_id,
            "run_completed",
            {
                "type": "run_completed",
                "run_id": run_id,
                "status": "completed",
            },
        ))
        return {
            "run_id": run_id,
            "status": self.STATUS_COMPLETED,
            "executed": executed or {},
            "result": result.to_dict(),
        }


def _safe_json(obj: Any) -> str:
    """安全 JSON 序列化（失败退回字符串）。"""
    try:
        return json.dumps(obj, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(obj)
