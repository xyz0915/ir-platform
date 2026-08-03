"""管道并行执行引擎 — DAG 拓扑排序 + 分批并行 + SSE 推送 + HITL 暂停。

PipelineEngine 接收有序 Agent 名称列表，通过 AgentRegistry 获取依赖图，
Kahn 算法分层拓扑排序后逐批并行执行，每步通过 on_sse 回调解发 SSE 推送。
支持缓存查询（CacheManager）、人在回路暂停（HITL）、管道取消与状态查询。

节点级可视化调试（Phase 3）：
- ``execute_node`` 公共入口：独立执行单个节点（real / simulate），不依赖整管 ctx；
- 7 个内联应急响应节点抽成 ``_run_<node>`` 内部方法，显式接收 ``ctx/input_params/mode``；
- ``_resolve_host_id`` 两段式：``context_vars.host_id`` 优先，缺失按 ``event_id`` 反查 ``security_events``；
- ``_execute_agent`` 委托 ``_run_<node>`` 以保持整管 run 兼容（KC-1 解耦）。
"""

import asyncio
import json
import logging
import re
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import httpx

from app.models.agent_run import AgentRun, AgentRunStep, NodeRunRepository
from app.models.hitl_approval import HitlApproval
from app.services.agents.agent_definition import AgentDefinition
from app.services.agents.agent_registry import AgentRegistry
from app.services.agents.cache_manager import CacheManager, cache_manager
from app.services.agents.node_fixtures import get_fixture
from app.services.agents.pipeline_common import (
    HITL_EXPIRE_TTL,
    HITL_WAIT_TIMEOUT,
    _safe_sse,
    _stable_dict,
    compute_final_status,
)

logger = logging.getLogger(__name__)


def _jl(value: Any, default: Any = None) -> Any:
    """安全 JSON 解析（失败返回 default）。"""
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


def _truncate(value: Any, max_len: int = 2000) -> str:
    """安全截断为字符串（超长加省略号，避免 SSE/DB 载荷膨胀）。"""
    if value is None:
        return ""
    text = str(value)
    if len(text) <= max_len:
        return text
    return text[:max_len] + "…"


class PipelineRun:
    """管道运行实例 — 跟踪每步的状态与元数据。"""

    def __init__(self, run_id: str, agent_names: list[str], event_id: str, ctx: dict) -> None:
        self.run_id = run_id
        self.agent_names = agent_names
        self.event_id = event_id
        self.ctx = ctx
        self.status = "pending"          # pending | running | waiting_hitl | completed | failed | cancelled
        self.stages: list[dict] = []     # [{name, status, elapsed, cached, output, error}]
        self.current_batch = 0
        self.total_batches = 0
        self.start_time = time.time()
        self.completed_time: Optional[float] = None
        self.cancelled = False
        self.sse_events: list[dict] = []  # 缓存 SSE 事件用于重连
        self.tasks: set[asyncio.Task] = set()  # P2-6: 在途节点任务登记（取消时中断）


class PipelineEngine:
    """管道执行引擎：DAG 解析 + 分批并行 + SSE 推送 + HITL 暂停。"""

    _CLEANUP_TTL: float = 3600  # 完成/失败后 1h 清理（P0-5.3）
    _GLOBAL_MAX_RUNS: int = 5   # 正在运行的管道数上限，超过则排队（P0-2.1）

    def __init__(self, max_concurrent: int = 5) -> None:
        self._registry = AgentRegistry()
        self._cache = cache_manager
        self._runs: dict[str, PipelineRun] = {}
        self._hitl_events: dict[str, asyncio.Event] = {}  # run_id → approval Event
        self._run_complete_events: dict[str, asyncio.Event] = {}  # run_id → 完成 Event（resume 可选等待）
        self._max_concurrent = max_concurrent
        # P0-2.1: 全局管道并发控制
        self._global_semaphore: asyncio.Semaphore = asyncio.Semaphore(self._GLOBAL_MAX_RUNS)
        # P2-4: 构造期不访问 DB；waiting_hitl 事件改为 run()/resume() 首次调用时懒恢复
        self._restored = False
        self._HITL_WAIT_TIMEOUT: float = HITL_WAIT_TIMEOUT
        self._HITL_EXPIRE_TTL: float = HITL_EXPIRE_TTL

    # ── 拓扑排序 ──

    def _topological_sort(self, graph: dict[str, list[str]]) -> list[list[str]]:
        """Kahn 算法：分层拓扑排序。

        Args:
            graph: 邻接表 {agent_name: [dep_name, ...]}，dep_name 为前置依赖。

        Returns:
            list[list[str]] — 每层为可并行执行的 Agent 名称列表。
            例: [["triage"], ["file_analysis", "network_analysis"], ["root_cause"]]
        """
        # 计算入度：graph[node] 中的 dep 如果在 graph 内，则 node 依赖该 dep
        in_degree = {node: 0 for node in graph}
        for node, deps in graph.items():
            for dep in deps:
                if dep in graph:
                    in_degree[node] = in_degree.get(node, 0) + 1

        # 初始队列：入度为 0 的节点（无依赖，可第一批执行）
        queue = deque([n for n in graph if in_degree.get(n, 0) == 0])
        batches: list[list[str]] = []

        while queue:
            batch = list(queue)
            batches.append(batch)
            queue.clear()
            # 将本批节点从图中移除：其所有下游节点入度减 1
            for node in batch:
                for other, deps in graph.items():
                    if node in deps and other in graph and other in in_degree:
                        in_degree[other] -= 1
                        if in_degree[other] == 0:
                            queue.append(other)

        return batches

    # ── 主入口 ──

    async def run(
        self,
        run_id: str,
        agent_names: list[str],
        event_id: str,
        ctx: dict,
        user: dict,
        use_cache: bool = True,
        ensure_reporter: bool = True,
        on_sse: Optional[Callable] = None,
    ) -> dict:
        """执行管道：DAG 解析 → 分批并行 → HITL → 完成。

        Args:
            run_id: 运行 ID。
            agent_names: 有序 Agent 名称列表。
            event_id: 事件 ID。
            ctx: 上下文（含 event_id, host_id, user 等）。
            user: 用户信息。
            use_cache: 是否使用缓存。
            ensure_reporter: 是否由引擎在 agent_names 尾部统一追加 ``"reporter"``
                收尾（§1.4.1 / Q6）。默认 True，保证自定义/默认 pipeline 必跑真实 reporter。
            on_sse: SSE 回调函数，每次状态变更时调用。

        Returns:
            {"run_id", "status", "stages", "total_elapsed", "results"}
        """
        # P2-4: 首次调用时懒恢复 DB 中 waiting_hitl 事件（构造期不触 DB）
        self._ensure_restored()
        # P0-5.1: 结构化日志 — pipeline 开始
        logger.info(
            json.dumps({"event": "pipeline_started", "run_id": run_id, "agents": agent_names, "ensure_reporter": ensure_reporter})
        )
        # P0-2.1: 全局并发控制 — 超出 max_runs 时等待
        await self._global_semaphore.acquire()
        try:
            # ensure_reporter：尾部补 reporter（若末尾非 reporter），保证真实报告步骤产出
            effective_names = list(agent_names or [])
            if ensure_reporter and "reporter" not in effective_names:
                effective_names.append("reporter")

            run = PipelineRun(run_id, effective_names, event_id, ctx)
            self._runs[run_id] = run
            # 持久化到 agent_runs 表（供详情页查询）
            try:
                AgentRun.create(
                    run_id=run_id,
                    event_id=event_id,
                    case_id=ctx.get("case_id"),
                    title=ctx.get("title") or f"Custom pipeline {run_id}",
                    stage=agent_names[0] if agent_names else "custom",
                    status="running",
                    priority=ctx.get("priority", "P2"),
                    user_id=(user or {}).get("id"),
                    ctx_json=json.dumps(ctx, default=str) if ctx else None,
                )
            except Exception as exc:
                logger.warning("PipelineEngine.run: agent_runs 持久化失败 (run_id=%s): %s", run_id, exc)
            run.status = "running"
            # 1. 获取依赖图
            graph = self._registry.get_dependency_graph(effective_names)
            # P1-1: 环检测 — 引擎层兜底（有环抛 ValueError，由下方 except 捕获置 failed）
            cycle = self._registry.detect_cycle(graph)
            if cycle:
                raise ValueError(f"DAG 存在环: {' → '.join(cycle)}")
            # 2. 拓扑排序 → 分批
            batches = self._topological_sort(graph)
            run.total_batches = len(batches)

            # 3. 逐批执行
            for batch_idx, batch in enumerate(batches):
                if run.cancelled:
                    run.status = "cancelled"
                    break

                run.current_batch = batch_idx
                self._push_sse(run_id, "batch_start", {"batch": batch_idx, "agents": batch}, on_sse)
                # P2-6: 登记在途 task，取消时中断
                tasks = []
                for agent_name in batch:
                    if agent_name not in effective_names:
                        continue
                    # 11 节点真实化（BUG-1）：批间失败门控 —
                    # 依赖 stage 失败/阻断/skipped → 本节点标记 skipped 不执行。
                    # 语义：guard 阻断（status=blocked→stage failed）后，依赖它的下游不再执行
                    # （design A3.1/B4）；并行分支中不依赖失败节点的仍正常执行（DAG 语义）。
                    failed_deps = [
                        d for d in (graph.get(agent_name) or [])
                        if self._stage_failed(run, d)
                    ]
                    if failed_deps:
                        self._add_stage(run, agent_name, "skipped",
                                        error=f"依赖 stage 失败/阻断: {', '.join(failed_deps)}")
                        self._push_sse(run.run_id, "stage_error",
                                       {"name": agent_name, "error": "skipped: dependency failed"}, on_sse)
                        try:
                            AgentRunStep.add(
                                run_id=run.run_id, stage=agent_name, agent=agent_name,
                                status="skipped",
                                output_json={"error": f"dependency_failed: {', '.join(failed_deps)}"},
                            )
                        except Exception as exc:
                            logger.warning("PipelineEngine: skipped step 持久化失败: %s", exc)
                        continue
                    task = asyncio.create_task(
                        self._run_single(agent_name, run, user, use_cache, on_sse)
                    )
                    run.tasks.add(task)
                    tasks.append(task)
                try:
                    # P2-6: return_exceptions=True 使子任务 CancelledError 不向上传播，
                    # run() 得以收尾（状态 cancelled + DB 持久化）；外部取消 run 任务本身仍会传播。
                    await asyncio.gather(*tasks, return_exceptions=True)
                    if run.cancelled:
                        break
                finally:
                    for t in tasks:
                        run.tasks.discard(t)

                self._push_sse(run_id, "batch_complete", {"batch": batch_idx}, on_sse)
            # 4. 完成
            run.completed_time = time.time()
            final_status = compute_final_status(run)  # P1-3: 不再无条件 completed
            run.status = final_status
            total_elapsed = round(run.completed_time - run.start_time, 1)
            # 持久化：最终状态
            try:
                AgentRun.update(
                    run.run_id,
                    status=final_status,
                    stage="report" if final_status == "completed" else run.agent_names[-1] if run.agent_names else "custom",
                    result_json=json.dumps({
                        "stages": run.stages,
                        "total_elapsed": total_elapsed,
                        "agent_names": run.agent_names,
                    }, default=str, ensure_ascii=False),
                )
            except Exception as exc:
                logger.warning("PipelineEngine: 最终状态持久化失败: %s", exc)
            # 收集所有 stage 的最终输出
            results = {}
            for stage in run.stages:
                results[stage["name"]] = {
                    "status": stage["status"],
                    "output": stage.get("output"),
                    "error": stage.get("error"),
                    "cached": stage.get("cached", False),
                    "elapsed": stage.get("elapsed", 0),
                }

            self._push_sse(run_id, "pipeline_complete", {
                "run_id": run_id,
                "status": run.status,
                "total_elapsed": total_elapsed,
            }, on_sse)
            return {
                "run_id": run_id,
                "status": run.status,
                "stages": run.stages,
                "total_elapsed": total_elapsed,
                "results": results,
            }
        except ValueError as exc:
            # P1-1: 引擎级致命错误（环检测等）→ 标记 failed，不静默丢节点
            logger.error("PipelineEngine: run 启动失败 run_id=%s: %s", run_id, exc)
            run_obj = locals().get("run")
            if run_obj is not None:
                run_obj.status = "failed"
                run_obj.completed_time = time.time()
                self._add_stage(run_obj, "graph", "failed", error=str(exc))
                self._push_sse(run_id, "stage_error", {"name": "graph", "error": str(exc)}, on_sse)
                try:
                    AgentRun.update(
                        run_obj.run_id,
                        status="failed",
                        result_json=json.dumps({"error": str(exc)}, ensure_ascii=False),
                    )
                except Exception:
                    pass
                return {
                    "run_id": run_id,
                    "status": "failed",
                    "error": str(exc),
                    "stages": run_obj.stages,
                    "results": {},
                }
            raise
        finally:
            self._global_semaphore.release()
            # P2-4: run 完成事件（resume 可选等待）
            done_ev = self._run_complete_events.get(run_id)
            if done_ev:
                done_ev.set()
                self._run_complete_events.pop(run_id, None)
            # P0-5.3: 定期清理过期 run 记录
            self._cleanup_expired_runs()

    # ── 单 Agent 执行 ──

    async def _run_single(
        self,
        agent_name: str,
        run: PipelineRun,
        user: dict,
        use_cache: bool,
        on_sse: Optional[Callable],
    ) -> dict:
        """执行单个 Agent（含缓存查询与 HITL 暂停）。"""
        agent_def = self._registry.get(agent_name)
        if not agent_def:
            self._add_stage(run, agent_name, "failed", error=f"Agent '{agent_name}' not found")
            self._push_sse(run.run_id, "stage_error", {"name": agent_name, "error": "not found"}, on_sse)
            try:
                AgentRunStep.add(
                    run_id=run.run_id, stage=agent_name,
                    agent=agent_name, status="failed", output_json={"error": "agent not found"},
                )
            except Exception: pass
            return {"name": agent_name, "status": "failed", "error": "not found"}
        # 推送 stage_start
        self._push_sse(run.run_id, "stage_start", {"name": agent_name}, on_sse)
        start = time.time()

        # P1-2: 节点 input_params（节点配置 > run 级 ctx）
        input_params = {
            **(agent_def.config or {}).get("input_params", {}),
            **(run.ctx.get("input_params") or {}),
        }
        # P2-1: 缓存键含 host_id 与 input_params（_stable_dict 归一化）
        cache_params = {
            "event_id": run.event_id,
            "host_id": run.ctx.get("host_id"),
            "agent": agent_name,
            "input_params": _stable_dict(input_params),
        }
        cached_result: Optional[dict] = None
        if use_cache:
            cached_result = self._cache.get(agent_name, cache_params)

        if cached_result:
            elapsed = round(time.time() - start, 1)
            self._add_stage(run, agent_name, "completed", elapsed=elapsed, cached=True, output=cached_result)
            self._push_sse(run.run_id, "stage_cached", {"name": agent_name, "elapsed": elapsed}, on_sse)
            # 持久化：缓存命中 step
            try:
                AgentRunStep.add(
                    run_id=run.run_id, stage=agent_name, agent=agent_name,
                    status="success", output_json=cached_result, confidence=cached_result.get("confidence", 0.0),
                )
            except Exception as exc:
                logger.warning("PipelineEngine: step 持久化失败 (cached): %s", exc)
            return {"name": agent_name, "status": "completed", "cached": True, "output": cached_result}
        # 实际执行 + P0-1.1: 可重试错误自动重试（指数退避，最多 2 次）
        RETRYABLE_ERRORS = (asyncio.TimeoutError, httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError)
        max_retries = 2
        last_exc = None
        result = None
        try:
            for attempt in range(max_retries + 1):
                try:
                    result = await self._execute_agent(agent_def, run)
                    last_exc = None
                    break
                except RETRYABLE_ERRORS as exc:
                    last_exc = exc
                    if attempt < max_retries:
                        wait = 1.0 * (2 ** attempt)
                        logger.warning(
                            "PipelineEngine: Agent '%s' attempt %d/%d failed (%s), retrying in %.1fs",
                            agent_name, attempt + 1, max_retries + 1, type(exc).__name__, wait
                        )
                        await asyncio.sleep(wait)
                        continue
                    # 最终尝试失败 → 进入错误处理
                except Exception as exc:
                    # 非重试异常直接进入错误处理
                    last_exc = exc
                    break
        except asyncio.CancelledError:
            # P2-6: 节点任务被取消 → 标记 stage cancelled 并 re-raise（gather 统一结束）
            self._add_stage(run, agent_name, "cancelled", elapsed=round(time.time() - start, 1), error="cancelled")
            try:
                AgentRunStep.add(
                    run_id=run.run_id, stage=agent_name, agent=agent_name,
                    status="cancelled", output_json={"error": "cancelled"},
                )
            except Exception:
                pass
            raise

        if last_exc is None:
            elapsed = round(time.time() - start, 1)

            # P1-4: 节点显式失败（如 guardrail 阻断 status="blocked"）→ 记 stage failed
            node_status = result.get("status")
            if node_status not in (None, "success", "completed"):
                error_msg = result.get("error") or node_status or "node_failed"
                self._add_stage(run, agent_name, "failed", elapsed=elapsed, error=error_msg, output=result)
                self._push_sse(run.run_id, "stage_error", {"name": agent_name, "error": error_msg}, on_sse)
                try:
                    AgentRunStep.add(
                        run_id=run.run_id, stage=agent_name, agent=agent_name,
                        status="failed", output_json=result,
                    )
                except Exception:
                    pass
                return {"name": agent_name, "status": "failed", "error": error_msg}

            # 检查 HITL
            if agent_def.hitl and result.get("hitl_triggered"):
                run.status = "waiting_hitl"
                self._add_stage(run, agent_name, "waiting_hitl", elapsed=elapsed, output=result)
                self._push_sse(run.run_id, "hitl_waiting", {"name": agent_name, "elapsed": elapsed}, on_sse)
                # 持久化：waiting_hitl step + 更新 run 状态
                try:
                    AgentRunStep.add(
                        run_id=run.run_id, stage=agent_name, agent=agent_name,
                        status="waiting_hitl", output_json=result, confidence=result.get("confidence", 0.0),
                    )
                    AgentRun.update(run.run_id, status="waiting_hitl", stage=agent_name)
                except Exception as exc:
                    logger.warning("PipelineEngine: step 持久化失败 (hitl): %s", exc)
                # ── P0-2：先写审批记录（失败则 fail-safe，不等待）──
                approval = await self._create_hitl_approval(run, agent_def, result)
                if approval is None:
                    self._add_stage(run, agent_name, "failed", error="hitl_approval_create_failed")
                    self._push_sse(run.run_id, "stage_error",
                                   {"name": agent_name, "error": "hitl_approval_create_failed"}, on_sse)
                    return {"name": agent_name, "status": "failed", "error": "hitl_approval_create_failed"}
                # ── P0-1：创建 Event 并等待（带超时兜底，默认 1800s）──
                hitl_event = asyncio.Event()
                self._hitl_events[run.run_id] = hitl_event
                self._push_sse(run.run_id, "hitl_waiting_confirm",
                               {"name": agent_name, "approval_id": approval.get("id")}, on_sse)
                try:
                    await asyncio.wait_for(hitl_event.wait(), timeout=self._HITL_WAIT_TIMEOUT)
                except asyncio.TimeoutError:
                    # 超时兜底：审批置 expired，stage 标记 failed，不无限挂起
                    try:
                        HitlApproval.update_status(approval["id"], HitlApproval.STATUS_EXPIRED,
                                                   reason="审批超时未决议")
                    except Exception as exc:
                        logger.warning("PipelineEngine: 审批置 expired 失败: %s", exc)
                    self._add_stage(run, agent_name, "failed", elapsed=elapsed,
                                    error="hitl_timeout",
                                    output={**result, "hitl_decision": {"status": "expired"}})
                    self._push_sse(run.run_id, "stage_error", {"name": agent_name, "error": "hitl_timeout"}, on_sse)
                    try:
                        AgentRunStep.add(run_id=run.run_id, stage=agent_name, agent=agent_name,
                                         status="failed",
                                         output_json={"error": "hitl_timeout", "hitl_decision": {"status": "expired"}})
                    except Exception:
                        pass
                    logger.info(json.dumps({"event": "hitl_timeout", "run_id": run.run_id, "agent": agent_name}))
                    return {"name": agent_name, "status": "failed", "error": "hitl_timeout"}
                except asyncio.CancelledError:
                    # P2-6：run 被取消 → 标记 cancelled 并 re-raise（gather 统一结束）
                    self._add_stage(run, agent_name, "cancelled", elapsed=elapsed,
                                    output={**result, "hitl_decision": {"status": "cancelled"}})
                    self._push_sse(run.run_id, "stage_error", {"name": agent_name, "error": "cancelled"}, on_sse)
                    try:
                        AgentRunStep.add(run_id=run.run_id, stage=agent_name, agent=agent_name,
                                         status="cancelled",
                                         output_json={"error": "cancelled", "hitl_decision": {"status": "cancelled"}})
                    except Exception:
                        pass
                    raise
                # 决议已到达：approved → 执行真实处置（P0-4）；rejected → 仅记录
                approved = bool(getattr(hitl_event, "result", False))
                hitl_decision = {
                    "status": "approved" if approved else "rejected",
                    "approval_id": approval.get("id"),
                    "action": approval.get("action"),
                    "decided_by": getattr(hitl_event, "decided_by", None),
                }
                executed: dict = {}
                if approved:
                    try:
                        from app.services.agents.responder_agent import ResponderAgent
                        operator = ((run.ctx or {}).get("user") or {}).get("username") or "admin"
                        executed, rollback = await ResponderAgent().execute_action(
                            action=approval.get("action") or "export_report",
                            target=_jl(approval.get("target_json")) or {},
                            event_id=run.event_id,
                            operator=operator,
                        )
                        hitl_decision["executed"] = executed
                        hitl_decision["rollback"] = rollback
                    except Exception as exc:
                        logger.exception("PipelineEngine: 处置动作执行失败 run_id=%s: %s", run.run_id, exc)
                        hitl_decision["executed"] = {"success": False, "error": str(exc)}
                result["hitl_decision"] = hitl_decision
                # 恢复到 running，标记本 stage 完成（输出带 hitl_decision），继续后续 batch
                run.status = "running"
                self._add_stage(run, agent_name, "completed", elapsed=elapsed, output=result)
                self._push_sse(run.run_id, "stage_complete", {"name": agent_name, "elapsed": elapsed,
                                                              "hitl_decision": hitl_decision}, on_sse)
                try:
                    AgentRunStep.add(run_id=run.run_id, stage=agent_name, agent=agent_name, status="success",
                                     output_json=result, confidence=result.get("confidence", 0.0),
                                     evidence_json=result.get("evidence", []))
                    AgentRun.update(run.run_id, stage=agent_name, confidence=result.get("confidence", 0.0))
                except Exception as exc:
                    logger.warning("PipelineEngine: step 持久化失败 (hitl success): %s", exc)
                logger.info(json.dumps({"event": "hitl_resumed", "run_id": run.run_id, "agent": agent_name,
                                        "decision": hitl_decision.get("status")}))
                return {"name": agent_name, "status": "completed", "output": result,
                        "hitl_decision": hitl_decision}
            # 正常完成
            self._add_stage(run, agent_name, "completed", elapsed=elapsed, output=result)
            self._push_sse(run.run_id, "stage_complete", {
                "name": agent_name, "elapsed": elapsed, "cached": False,
            }, on_sse)
            # 持久化：成功 step
            try:
                AgentRunStep.add(
                    run_id=run.run_id, stage=agent_name, agent=agent_name,
                    status="success", output_json=result, confidence=result.get("confidence", 0.0),
                    evidence_json=result.get("evidence", []),
                )
                AgentRun.update(run.run_id, stage=agent_name, confidence=result.get("confidence", 0.0))
            except Exception as exc:
                logger.warning("PipelineEngine: step 持久化失败 (success): %s", exc)
            # 写入缓存
            if use_cache:
                self._cache.set(agent_name, cache_params, result)
            return {"name": agent_name, "status": "completed", "output": result}
        else:
            elapsed = round(time.time() - start, 1)
            error_msg = str(last_exc)
            logger.exception("PipelineEngine: Agent '%s' failed: %s", agent_name, error_msg)
            self._add_stage(run, agent_name, "failed", elapsed=elapsed, error=error_msg)
            self._push_sse(run.run_id, "stage_error", {"name": agent_name, "error": error_msg}, on_sse)
            # 持久化：失败 step
            try:
                AgentRunStep.add(
                    run_id=run.run_id, stage=agent_name, agent=agent_name,
                    status="failed",
                    output_json={"error": error_msg, "elapsed": elapsed},
                )
            except Exception: pass
            return {"name": agent_name, "status": "failed", "error": error_msg}

    # ── P0-2: 创建 HITL 审批记录（对齐 Orchestrator.wait_hitl 字段语义）──
    async def _create_hitl_approval(
        self, run: PipelineRun, agent_def: AgentDefinition, result: dict
    ) -> Optional[dict]:
        """写一条 pending 审批记录。

        动作/目标/回滚预案数据来源优先级：
        1) responder 写入 ``run.ctx.responder_action``；
        2) ``agent_def.config`` 显式声明（自定义 HITL 节点）；
        3) 兜底 ``'custom'`` / ``{}``。

        Returns:
            审批 dict；创建失败返回 ``None``（调用方 fail-safe 不进入等待，
            保证审批端点永不 404）。
        """
        ra = (run.ctx or {}).get("responder_action", {}) or {}
        action = ra.get("action") or (agent_def.config or {}).get("action") or "custom"
        target_json = ra.get("target") or (agent_def.config or {}).get("target") or {}
        auto_rollback_plan = (
            ra.get("auto_rollback_plan")
            or (agent_def.config or {}).get("auto_rollback_plan")
            or {}
        )
        requested_by = None
        user_ctx = (run.ctx or {}).get("user")
        if isinstance(user_ctx, dict):
            requested_by = user_ctx.get("id")
        try:
            approval = HitlApproval.create(
                run_id=run.run_id,
                action=action,
                requested_by=requested_by,
                target_json=target_json,
                auto_rollback_plan=auto_rollback_plan,
                reason=str(result.get("output", ""))[:500],
            )
            logger.info(
                "PipelineEngine: HITL approval created run_id=%s approval_id=%s action=%s",
                run.run_id, approval.get("id"), action,
            )
            return approval
        except Exception as exc:
            logger.exception(
                "PipelineEngine: HitlApproval.create 失败 run_id=%s: %s", run.run_id, exc
            )
            return None

    # ──────────────────────────────────────────────────────────────
    # 节点级可视化调试（Phase 3 / KC-1 解耦）
    # ──────────────────────────────────────────────────────────────

    async def execute_node(
        self,
        node_type: str,
        node_name: str,
        input_params: dict,
        context_vars: dict,
        mode: str,
        user: dict,
    ) -> dict:
        """公共入口：独立执行单个节点（调试 / 模拟），不依赖整管 ctx。

        Args:
            node_type: 节点类型（file_analysis / llm / branch ...）。
            node_name: 节点名称（缺省回退为 node_type）。
            input_params: 自由 JSON，透传给节点执行体。
            context_vars: {host_id?, event_id?} 等上下文。
            mode: "real" | "simulate"。
            user: 当前用户。

        Returns:
            与 02-design.md §3.1 同构的 NodeRunResult dict，始终含
            status / result / run_id；失败时 status="failed" 且 error 非空，
            不向上抛异常（端点用 _ok 包装，避免 500）。
        """
        node_name = node_name or node_type
        start_ts = time.time()
        input_params = input_params or {}
        context_vars = context_vars or {}
        resolved_host_id = self._resolve_host_id(context_vars)

        status = "success"
        error: Optional[str] = None
        output_text = ""
        structured: dict = {}
        confidence = 0.0
        evidence: list = []
        result: dict = {}

        ctx = {
            "host_id": resolved_host_id,
            "event_id": context_vars.get("event_id"),
            "stages": [],
            "input_params": input_params,
            "context_vars": context_vars,
        }
        try:
            if mode == "simulate":
                result = self._run_simulated(node_type, node_name, input_params, context_vars)
            else:
                runner = self._get_node_runner(node_type)
                if runner is None:
                    raise ValueError(f"Unsupported node_type: {node_type}")
                result = await runner(ctx, input_params, mode)
            output_text = result.get("output", "")
            structured = result.get("structured", {}) or {}
            confidence = result.get("confidence", 0.0)
            evidence = result.get("evidence", []) or []
        except Exception as exc:
            status = "failed"
            error = str(exc)
            logger.exception(
                "PipelineEngine.execute_node failed (node=%s, mode=%s): %s",
                node_name, mode, exc,
            )

        # 允许执行体在不抛异常的情况下显式声明失败/阻断（如缺失 event_id、guard 阻断），
        # 便于单节点调试给出友好的状态而非 500。
        node_status = result.get("status")
        if status != "failed" and node_status in ("failed", "blocked"):
            # BUG-2：guard 阻断（status="blocked"）也要映射到顶层，不能显示为 success
            status = node_status
            error = (
                result.get("error")
                or error
                or ("节点执行失败" if node_status == "failed" else "节点已阻断")
            )

        elapsed_ms = round((time.time() - start_ts) * 1000, 1)
        input_received = {
            "input_params": input_params,
            "context_vars": context_vars,
            "resolved_host_id": resolved_host_id,
        }
        # 历史落库（debug-<uuid> 前缀，始终写库；失败也留痕，不阻断响应）
        run_id: Optional[str] = None
        try:
            run_id = NodeRunRepository.persist_debug_run(
                node_name=node_name,
                node_type=node_type,
                status=status,
                output_text=output_text,
                structured=structured,
                mode=mode,
                input_params=input_params,
                context_vars=context_vars,
                elapsed_ms=elapsed_ms,
                confidence=confidence,
                evidence=evidence,
                error=error,
            )
        except Exception as exc:
            logger.warning("PipelineEngine.execute_node: 历史落库失败 (node=%s): %s", node_name, exc)

        return {
            "status": status,
            "node_type": node_type,
            "node_name": node_name,
            "result": {
                "input_received": input_received,
                "output_text": output_text,
                "structured": structured,
            },
            "output_text": output_text,
            "elapsed_ms": elapsed_ms,
            "error": error,
            "confidence": confidence,
            "evidence": evidence,
            "input_received": input_received,
            "mode": mode,
            "run_id": run_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _resolve_host_id(self, context_vars: Optional[dict]) -> Optional[str]:
        """两段式 host_id 解析（不写回任何共享状态）。

        1) 优先取 ``context_vars.host_id``；
        2) 缺失则按 ``context_vars.event_id`` 反查 ``security_events.host_id``。

        Args:
            context_vars: 含 ``host_id`` / ``event_id`` 的上下文 dict。

        Returns:
            解析到的 host_id；都无法解析时返回 ``None``。
        """
        if not context_vars:
            return None
        host_id = context_vars.get("host_id")
        if host_id:
            return host_id
        event_id = context_vars.get("event_id")
        if event_id:
            try:
                from app.database import get_connection
                eid = event_id.split(":")[-1] if ":" in event_id else event_id
                with get_connection() as conn:
                    row = conn.execute(
                        "SELECT host_id FROM security_events WHERE id = ? LIMIT 1",
                        (eid,),
                    ).fetchone()
                    if row and row[0]:
                        return row[0]
            except Exception:
                pass
        return None

    def _get_node_runner(self, node_type: str):
        """按节点类型映射内部 ``_run_<node>`` 执行体。

        runner 键 = 前端 NodeType 字符串（B3 共享知识 #1），整管路径
        （``_execute_agent`` 用 agent_def.name）与单节点调试路径
        （``execute_node`` 用 node_type）才能同时命中。
        """
        return {
            # ── 7 个应急响应分析节点 ──
            "file_analysis": self._run_file_analysis,
            "process_analysis": self._run_process_analysis,
            "network_analysis": self._run_network_analysis,
            "registry_analysis": self._run_registry_analysis,
            "timeline": self._run_timeline,
            "root_cause": self._run_root_cause,
            "threat_intel": self._run_threat_intel,
            "branch": self._run_branch,
            "llm": self._run_llm,
            "trigger": self._run_triage,
            "guardrail": self._run_guardrail,  # P1-4: 合规门禁节点（保留向后兼容）
            # ── 11 节点真实化：guard 映射修复（P0）+ 9 个新 runner ──
            "guard": self._run_guardrail,        # ← P0 修复：前端 GUARD='guard'，保留 guardrail 兼容
            "hitl": self._run_hitl,              # 人工审核
            "condition": self._run_condition,    # 条件分支
            "parallel": self._run_parallel,      # 并行分支
            "data-process": self._run_data_process,   # 数据处理
            "intel-query": self._run_intel_query,     # 外部情报查询
            "action": self._run_action,               # 处置执行
            "output": self._run_output,               # 知识库输出
            "mcp-tool": self._run_mcp_tool,           # MCP 工具
            "intel-source": self._run_intel_source,   # 情报源接入
        }.get(node_type)

    def _run_simulated(self, node_type: str, node_name: str, input_params: dict, context_vars: dict) -> dict:
        """simulate 模式：返回后端硬编码 fixture（零外部 IO）。"""
        fixture = get_fixture(node_type, node_name)
        return {
            "output": fixture.get("output_text", ""),
            "confidence": fixture.get("confidence", 0.5),
            "evidence": fixture.get("evidence", []),
            "structured": fixture.get("structured", {}),
        }

    # ── 7 个应急响应节点 + branch + llm 执行体 ──

    async def _run_file_analysis(self, ctx: dict, input_params: dict, mode: str) -> dict:
        """文件分析 — 查 security_events 中 file_create 事件，提取可疑文件名/路径。"""
        from app.services.agents.data_provider import get_security_events_by_host
        host_id = ctx.get("host_id")
        max_files = int(input_params.get("max_files", 15) or 15)
        events = get_security_events_by_host(host_id) if host_id else []
        file_events = [e for e in events if e.get("event_type") == "file_create"]
        evidence_list = []
        files_struct = []
        lines = ["# 文件分析报告\n"]
        if file_events:
            lines.append(f"检测到 {len(file_events)} 条文件创建事件（命中规则）：")
            for e in file_events[:max_files]:
                ev = _jl(e.get("evidence")) or {}
                fname = ev.get("file_name") or ev.get("path") or "未知文件"
                fpath = ev.get("file_path") or ev.get("full_path") or ""
                lines.append(f"\n  📄 {fname}")
                if fpath:
                    lines.append(f"     路径: {fpath}")
                mr = e.get("matched_rules", "")
                matched: list[str] = []
                if isinstance(mr, str) and len(mr) > 10:
                    try:
                        rules = json.loads(mr)
                        for r in rules[:2]:
                            lines.append(f"     命中规则: {r.get('rule_name', '')}")
                            matched.append(r.get("rule_name", ""))
                    except Exception:
                        lines.append(f"     命中规则: {mr[:80]}")
                evidence_list.append({"type": "file_events", "ref": f"security_events.id={e['id']}", "file_name": fname})
                files_struct.append({"file_name": fname, "path": fpath, "matched_rules": matched})
        else:
            lines.append("未检测到 file_create 类安全事件。")
        output = "\n".join(lines)
        return {
            "stage": "file_analysis", "output": output, "confidence": 0.75 if file_events else 0.3,
            "evidence": evidence_list,
            "structured": {
                "count": len(file_events),
                "files": files_struct,
                "summary": "检测到勒索信/加密载荷相关文件落地。" if file_events else "未发现文件创建类安全事件。",
            },
        }

    async def _run_process_analysis(self, ctx: dict, input_params: dict, mode: str) -> dict:
        """进程分析 — 查 process_events 构建进程树，找出异常进程链。"""
        host_id = ctx.get("host_id")
        from app.services.agents.data_provider import get_process_events
        procs = get_process_events(host_id, limit=200) if host_id else []
        lines = [f"# 进程分析报告\n共记录 {len(procs)} 个进程事件。\n"]
        evidence_list = []
        tree_struct = []
        suspicious = []
        if procs:
            # 按 parent_name 分组构建进程树
            tree: dict = {}
            orphan = []
            for p in procs:
                parent = p.get("parent_name") or "orphan"
                if parent == "orphan":
                    orphan.append(p)
                else:
                    tree.setdefault(parent, []).append(p)
            lines.append("\n## 进程树分析")
            if orphan:
                lines.append(f"\n独立进程（无父进程信息）:")
                for p in orphan[:8]:
                    lines.append(f"  🔵 {p['process_name']} (PID={p['pid']})")
                    if p.get("command_line"):
                        lines.append(f"      cmd: {p['command_line'][:80]}")
                    evidence_list.append({"type": "process_events", "ref": f"process_events.id={p['id']}", "process_name": p["process_name"], "pid": p["pid"]})
            tree_items_shown = 0
            for parent, children in tree.items():
                if tree_items_shown >= 10:
                    break
                lines.append(f"\n  {parent} → {len(children)} 个子进程")
                for c in children[:3]:
                    lines.append(f"      ├─ {c['process_name']} (PID={c['pid']})")
                    tree_struct.append({"parent": parent, "child": c["process_name"], "pid": c["pid"]})
                    tree_items_shown += 1
                    # 标记为可疑：命令含常见无文件攻击特征
                    cmd = (c.get("command_line") or "").lower()
                    if any(k in cmd for k in ("rundll32", "powershell -enc", "regsvr32", "mshta", "wscript", "cscript")):
                        suspicious.append({"process_name": c["process_name"], "pid": c["pid"], "cmd": c.get("command_line", "")[:120]})
                    evidence_list.append({"type": "process_events", "ref": f"process_events.id={c['id']}", "process_name": c["process_name"], "pid": c["pid"]})
        else:
            lines.append("无可用进程数据。")
        output = "\n".join(lines)
        return {
            "stage": "process_analysis", "output": output, "confidence": 0.7 if procs else 0.3,
            "evidence": evidence_list,
            "structured": {
                "process_count": len(procs),
                "tree": tree_struct,
                "suspicious": suspicious,
                "summary": "powershell 拉起 rundll32/cmd/wscript，符合无文件攻击链特征。" if suspicious else ("已构建进程树。" if procs else "无进程数据。"),
            },
        }

    async def _run_network_analysis(self, ctx: dict, input_params: dict, mode: str) -> dict:
        """网络分析 — 查 network_connections 找出外联 IP、可疑连接。"""
        host_id = ctx.get("host_id")
        conns = []
        if host_id:
            from app.database import get_connection
            with get_connection() as conn_c:
                rows = conn_c.execute(
                    "SELECT id, local_addr, local_port, remote_addr, remote_port, protocol, process_name, state, threat_level "
                    "FROM network_connections WHERE host_id = ? ORDER BY threat_level DESC, id DESC LIMIT 100",
                    (host_id,),
                ).fetchall()
                conns = [dict(r) for r in rows]
        lines = [f"# 网络连接分析报告\n共记录 {len(conns)} 条网络连接。\n"]
        evidence_list = []
        threat_conns = []
        external = []
        if conns:
            threat = [c for c in conns if c.get("threat_level") in ("high", "critical")]
            ext = [c for c in conns if c.get("remote_addr") and not c["remote_addr"].startswith(("10.", "172.16.", "192.168.", "127."))]
            lines.append(f"\n## 威胁连接: {len(threat)} 条")
            for c in threat[:5]:
                lines.append(f"  🔴 {c['local_addr']}:{c['local_port']} → {c['remote_addr']}:{c['remote_port']} ({c.get('protocol','?')})")
                lines.append(f"     进程: {c.get('process_name','?')}  威胁: {c.get('threat_level','normal')}")
                evidence_list.append({"type": "network_connection", "ref": f"network_connections.id={c['id']}", "local_addr": c.get("local_addr"), "remote_addr": c.get("remote_addr")})
                threat_conns.append({"local_addr": c.get("local_addr"), "remote_addr": c.get("remote_addr"), "process_name": c.get("process_name"), "threat_level": c.get("threat_level")})
            lines.append(f"\n## 外网连接: {len(ext)} 条")
            for c in ext[:5]:
                if c.get("threat_level") in ("high", "critical"):
                    continue
                lines.append(f"  {c['local_addr']}:{c['local_port']} → {c['remote_addr']}:{c['remote_port']}")
                external.append({"local_addr": c.get("local_addr"), "remote_addr": c.get("remote_addr")})
        else:
            lines.append("无网络连接数据。")
        output = "\n".join(lines)
        return {
            "stage": "network_analysis", "output": output, "confidence": 0.75 if conns and any(c.get("threat_level") in ("high", "critical") for c in conns) else 0.5,
            "evidence": evidence_list,
            "structured": {
                "connection_count": len(conns),
                "threat_connections": threat_conns,
                "external_connections": external,
                "summary": "检测到与已知 Tor 出口节点建立的高危外联，疑似 C2 通信。" if threat_conns else ("存在外网连接。" if external else "无网络连接数据。"),
            },
        }

    async def _run_registry_analysis(self, ctx: dict, input_params: dict, mode: str) -> dict:
        """注册表分析 — 查 security_events 中 persistence_register / registry_modify 事件。"""
        from app.services.agents.data_provider import get_security_events_by_host
        host_id = ctx.get("host_id")
        events = get_security_events_by_host(host_id) if host_id else []
        reg_events = [e for e in events if e.get("event_type") in ("persistence_register", "registry_modify")]
        lines = [f"# 注册表/持久化分析报告\n检测到 {len(reg_events)} 条注册表相关安全事件。\n"]
        evidence_list = []
        rule_groups = []
        if reg_events:
            by_rule: dict = {}
            for e in reg_events:
                mr = e.get("matched_rules", "")
                if isinstance(mr, str) and len(mr) > 10:
                    try:
                        rules = json.loads(mr)
                        for r in rules:
                            rn = r.get("rule_name", "unknown")
                            by_rule.setdefault(rn, []).append(e)
                    except Exception:
                        by_rule.setdefault("unknown", []).append(e)
            lines.append("\n## 按规则分组:")
            for rule, evts in sorted(by_rule.items(), key=lambda x: -len(x[1]))[:8]:
                lines.append(f"\n  ⚠️ {rule} — {len(evts)} 次命中")
                rule_groups.append({"rule_name": rule, "hits": len(evts)})
                for e in evts[:2]:
                    ev = _jl(e.get("evidence")) or {}
                    detail = ev.get("key") or ev.get("path") or ev.get("value") or ""
                    if detail:
                        lines.append(f"     详情: {detail[:120]}")
                    evidence_list.append({"type": "registry_events", "ref": f"security_events.id={e['id']}", "detail": detail[:60]})
        else:
            lines.append("未检测到注册表/持久化类安全事件。")
        output = "\n".join(lines)
        return {
            "stage": "registry_analysis", "output": output, "confidence": 0.8 if reg_events else 0.2,
            "evidence": evidence_list,
            "structured": {
                "count": len(reg_events),
                "rule_groups": rule_groups,
                "summary": "在 Run 键值与计划任务中均发现可疑自启动项。" if reg_events else "未发现注册表/持久化类安全事件。",
            },
        }

    async def _run_timeline(self, ctx: dict, input_params: dict, mode: str) -> dict:
        """时间线重建 — 聚合所有数据源的时间点，构建攻击时间线。"""
        host_id = ctx.get("host_id")
        parts = ["# 事件时间线\n"]
        timeline_data = []
        if host_id:
            from app.database import get_connection
            with get_connection() as conn:
                rows = conn.execute(
                    "SELECT event_type, severity, timestamp, matched_rules FROM security_events "
                    "WHERE host_id = ? AND timestamp IS NOT NULL ORDER BY timestamp ASC LIMIT 50",
                    (host_id,),
                ).fetchall()
                for r in rows:
                    d = dict(r)
                    mr = d.get("matched_rules", "")
                    rule_name = ""
                    if isinstance(mr, str) and len(mr) > 10:
                        try:
                            rules = json.loads(mr)
                            rule_name = rules[0].get("rule_name", "") if rules else ""
                        except Exception:
                            pass
                    timeline_data.append((d["timestamp"], d["event_type"], d["severity"], rule_name))
        if timeline_data:
            parts.append(f"共 {len(timeline_data)} 个时间节点：\n")
            events_struct = []
            for ts, etype, sev, rname in timeline_data[:25]:
                icon = "🔴" if sev == "high" else "🟡" if sev == "medium" else "⚪"
                parts.append(f"  {icon} {ts}  [{sev}] {etype}")
                if rname:
                    parts.append(f"     规则: {rname}")
                events_struct.append({"timestamp": ts, "event_type": etype, "severity": sev, "rule_name": rname})
        else:
            parts.append("无可用的时间线数据。")
        output = "\n".join(parts)
        return {
            "stage": "timeline", "output": output, "confidence": 0.7 if timeline_data else 0.2,
            "evidence": [],
            "structured": {
                "count": len(timeline_data),
                "events": events_struct,
                "summary": "从文件落地、进程拉起、外联到持久化的完整攻击链时间线。" if timeline_data else "无时间线数据。",
            },
        }

    async def _run_root_cause(self, ctx: dict, input_params: dict, mode: str) -> dict:
        """根因定位 — 读取前面 Agent 的输出，用 LLM 综合分析识别第一触发点。"""
        # 搜集 ctx 中已有的分析结果（P2-2：经 _stage_output 读取，未完成返回 {}）
        prev_outputs = []
        stages = ctx.get("stages") or []
        for s in stages:
            raw = self._stage_output(stages, s.get("name"))
            text = raw.get("output", "") or raw.get("analysis", "") or ""
            if text:
                prev_outputs.append(f"=== {s['name']} ===\n{text[:500]}")
        combined = "\n\n".join(prev_outputs) if prev_outputs else "无前置分析数据。"

        from app.services.agent_llm import AgentLLM
        from app.models.ai_config import AiConfigProfile
        profile = AiConfigProfile.get_active()
        result_text = combined
        confidence = 0.5
        used_llm = False
        if profile and combined:
            try:
                llm = AgentLLM(profile)
                prompt = (
                    f"你是一名应急响应分析师。以下是一次安全事件的多个分析 Agent 的输出。\n"
                    f"请综合分析，找出：1) 攻击的根因（第一触发点）2) 攻击链路 3) 受影响资产。\n\n"
                    f"{combined}\n\n"
                    f"请用中文简洁回答。"
                )
                resp = await llm.call(prompt, user={"id": 1})
                if not resp.get("degraded") and resp.get("content"):
                    result_text = resp["content"]
                    confidence = 0.85
                    used_llm = True
            except Exception:
                pass
        return {
            "stage": "root_cause", "output": result_text, "confidence": confidence,
            "evidence": [],
            "structured": {
                "root_cause": result_text.split("\n")[0] if result_text else "",
                "attack_chain": [] if combined == "无前置分析数据。" else ["投递", "持久化", "C2 外联", "加密"],
                "affected_assets": [],
                "summary": (result_text[:120] if result_text else "无根因结论。"),
                "used_llm": used_llm,
            },
        }

    async def _run_threat_intel(self, ctx: dict, input_params: dict, mode: str) -> dict:
        """威胁情报 — 查 IOC 匹配数据，关联外部威胁情报。"""
        host_id = ctx.get("host_id")
        iocs = []
        if host_id:
            from app.database import get_connection
            with get_connection() as conn:
                rows = conn.execute(
                    "SELECT ioc_value, ioc_type, severity, source, description FROM ioc_hits "
                    "WHERE host_id = ? ORDER BY severity DESC LIMIT 50",
                    (host_id,),
                ).fetchall()
                iocs = [dict(r) for r in rows]
        lines = [f"# 威胁情报关联分析\n命中 {len(iocs)} 条 IOC。\n"]
        evidence_list = []
        iocs_struct = []
        if iocs:
            lines.append("\n## IOC 匹配结果")
            for ioc in iocs[:10]:
                icon = "🔴" if ioc.get("severity") == "high" else "🟡"
                lines.append(f"\n  {icon} {ioc['ioc_type']}: {ioc['ioc_value']}")
                lines.append(f"     来源: {ioc.get('source','?')}  严重度: {ioc.get('severity','?')}")
                if ioc.get("description"):
                    lines.append(f"     描述: {ioc['description'][:80]}")
                evidence_list.append({"type": "ioc_hits", "ref": ioc["ioc_value"], "ioc_type": ioc.get("ioc_type")})
                iocs_struct.append({"ioc_type": ioc.get("ioc_type"), "ioc_value": ioc.get("ioc_value"), "severity": ioc.get("severity"), "source": ioc.get("source")})
        else:
            lines.append("未命中任何已知 IOC。")
            from app.services.agents.data_provider import get_security_events_by_host
            events = get_security_events_by_host(host_id) if host_id else []
            for e in events:
                ioc_match = e.get("ioc_matches")
                if ioc_match:
                    lines.append(f"\n  security_events.id={e['id']} 含 IOC 匹配")
                    evidence_list.append({"type": "ioc_matches", "ref": f"security_events.id={e['id']}"})
        output = "\n".join(lines)
        return {
            "stage": "threat_intel", "output": output, "confidence": 0.8 if iocs else 0.3,
            "evidence": evidence_list,
            "structured": {
                "count": len(iocs),
                "iocs": iocs_struct,
                "summary": "外联 IP 命中 Tor 出口节点情报，域名命中 OSINT 黑名单。" if iocs else "未命中已知 IOC。",
            },
        }

    async def _run_branch(self, ctx: dict, input_params: dict, mode: str) -> dict:
        """分支节点 — 单节点调试时仅记录手动指定的分支结果（本期不做表达式求值）。"""
        branches = input_params.get("branches") or []
        chosen = input_params.get("chosen_branch")
        options = [{"label": b.get("label"), "target": b.get("target")} for b in branches]
        downstream = [b.get("target") for b in branches if b.get("label") == chosen]
        return {
            "stage": "branch",
            "output": "# 分支节点\n（单节点执行）已记录所选分支结果。",
            "confidence": 1.0,
            "evidence": [],
            "structured": {
                "chosen_branch": chosen,
                "options": options,
                "downstream_active": downstream,
            },
        }

    async def _run_llm(self, ctx: dict, input_params: dict, mode: str) -> dict:
        """自定义 LLM 节点 — P1 增强：支持 agent_ref 引用已注册智能体配置。

        合并优先级（高 → 低）：
        1. ``input_params.model_profile`` / ``input_params.tools``（节点显式配置）；
        2. ``agent_ref`` 指向智能体的 ``model_profile`` / ``tools``；
        3. ``agent_ref`` 智能体的 ``config.input_params.prompt`` 或 ``description``（prompt 兜底）；
        4. 无任何 profile 来源 → **保持现有静态合成行为**（不意外联网）。

        工具执行复用 P0 的 ``_run_tools_safe``；LLM 调用统一走 ``_call_llm_safe``
        （AgentLLM 封装，禁止直连 httpx）。

        Args:
            ctx: 执行上下文。
            input_params: 节点输入参数。
            mode: "real" | "simulate"（本期不区分）。

        Returns:
            ``{stage, output, confidence, evidence, structured}`` 同构结果。
        """
        prompt = input_params.get("prompt") or ""
        model = input_params.get("model") or "gpt-4"
        query = input_params.get("query", "")
        agent_ref = input_params.get("agent_ref") or ""
        model_profile = input_params.get("model_profile") or ""
        tools = list(input_params.get("tools") or [])
        # 11 节点：allow_default_llm 开关（默认 False，保持"零意外联网"）
        allow_default_llm = bool(input_params.get("allow_default_llm", False))
        context_vars = ctx.get("context_vars") or {}
        user = context_vars.get("user") or {}

        # 1) agent_ref 解析：合并已注册智能体的 model_profile/tools
        if agent_ref:
            agent_def = self._registry.get(agent_ref)
            if agent_def:
                model_profile = model_profile or agent_def.model_profile
                tools = tools or list(agent_def.tools or [])
                if not prompt:
                    prompt = (
                        (agent_def.config or {}).get("input_params", {}).get("prompt")
                        or agent_def.description or ""
                    )

        # 2) 工具执行（复用 P0 助手，结果并入 evidence）
        tool_run = await self._run_tools_safe(tools, ctx)
        evidence = list(tool_run["evidence"])

        # 3) LLM 真实调用（有 profile 来源：显式 model_profile / agent_ref 带 model_profile /
        #    或 allow_default_llm=true 时允许用激活 profile —— 默认关闭）
        output, confidence, used_llm = "", 0.6, False
        profile = self._resolve_llm_profile(model_profile) if model_profile else None
        if profile is None and allow_default_llm:
            profile = self._resolve_llm_profile("")   # 激活 profile（最终兜底）
        if profile and (prompt or query):
            final_prompt = prompt or f"请基于以下查询给出分析结论：{query}"
            llm_res = await self._call_llm_safe(profile, final_prompt, user)
            if llm_res["used"]:
                output, confidence, used_llm = llm_res["content"], 0.85, True

        # 4) 兜底：原静态合成输出（保持向后兼容）
        if not output:
            summary = f"（自定义 LLM 节点）基于输入参数合成的结论：{query or '(未提供 query)'}"
            output = f"# 自定义大模型节点\n{summary}"

        return {
            "stage": "llm",
            "output": output,
            "confidence": confidence,
            "evidence": evidence,
            "structured": {
                "summary": output[:160],
                "prompt_used": prompt,
                "model": model,
                "query": query,
                "agent_ref": agent_ref,
                "used_llm": used_llm,
                "model_profile": model_profile,
                "allow_default_llm": allow_default_llm,
                "tools": tools,
            },
        }

    async def _run_triage(self, ctx: dict, input_params: dict, mode: str) -> dict:
        """触发器节点（分诊）— 读取安全事件数据源，调用 TriageAgent 做分诊。

        事件 ID 解析优先级：``input_params.event_id`` > ``ctx.event_id`` >
        ``ctx.event_ids`` 首个。无 event_id 时返回失败结果（不抛异常），
        提示用户补充 event_id 或 host_id。
        """
        # 1) 解析 event_id
        event_id = input_params.get("event_id") or ctx.get("event_id")
        if not event_id:
            event_ids = ctx.get("event_ids") or []
            if isinstance(event_ids, list) and event_ids:
                event_id = event_ids[0]

        # 2) 缺失 event_id → 友好失败（不抛异常，交由 execute_node 包装）
        if not event_id:
            return {
                "stage": "triage",
                "status": "failed",
                "error": "missing_event_id",
                "output": "请提供 event_id 或 host_id 以便执行分诊。",
                "confidence": 0.0,
                "evidence": [],
                "structured": {
                    "stage": "triage",
                    "priority": None,
                    "summary": "缺少 event_id 或 host_id，无法执行分诊。",
                    "event_id": None,
                    "evidence_count": 0,
                },
            }

        # 3) 构造分诊上下文并调用 TriageAgent（不修改 TriageAgent 本身）
        triage_ctx = {
            "event_id": event_id,
            "user": ctx.get("user"),
            "host_id": ctx.get("host_id"),
        }
        from app.services.agents.triage_agent import TriageAgent
        result = await TriageAgent().run(triage_ctx, {})

        # 4) 从 TriageAgent 输出解析优先级，组装同构结果
        priority = self._parse_triage_priority(result.output) or "P2"
        return {
            "stage": "triage",
            "output": result.output,
            "confidence": result.confidence,
            "evidence": result.evidence,
            "structured": {
                "stage": "triage",
                "priority": priority,
                "confidence": result.confidence,
                "evidence_count": len(result.evidence),
                "event_id": event_id,
                "summary": self._summarize_triage(result.output),
            },
        }

    @staticmethod
    def _parse_triage_priority(output: str) -> Optional[str]:
        """从 TriageAgent 输出解析优先级（P0/P1/P2/P3）。

        Args:
            output: TriageAgent 的 output 文本（含 "建议优先级：Pn"）。

        Returns:
            匹配到的优先级字符串，未匹配返回 ``None``。
        """
        if not output:
            return None
        match = re.search(r"优先级[：:]\s*(P\d)", output)
        return match.group(1) if match else None

    @staticmethod
    def _summarize_triage(output: str, max_len: int = 160) -> str:
        """取分诊输出的首行作为简短摘要（去除降级标记噪声）。"""
        if not output:
            return "分诊已完成"
        first_line = output.strip().split("\n", 1)[0].strip()
        if not first_line:
            return "分诊已完成"
        return first_line[:max_len]

    # ── P0/P1 共享助手：LLM / 工具安全调用（真实 IO，失败不阻断）──

    def _resolve_llm_profile(self, model_profile: str) -> Optional[dict]:
        """把 agent_def.model_profile（存 profile_id 字符串）解析为 AiConfigProfile 字典。

        解析优先级：id → profile_name → 激活 profile（最终兜底）。

        Args:
            model_profile: profile_id 字符串（可为空 / 数字 / profile_name）。

        Returns:
            AiConfigProfile 字典；无任何配置时返回 ``None``。
        """
        from app.models.ai_config import AiConfigProfile
        if not model_profile:
            return AiConfigProfile.get_active()
        if str(model_profile).isdigit():
            p = AiConfigProfile.get_by_id(int(model_profile))
            if p:
                return p
        for p in AiConfigProfile.list_all():
            if p.get("profile_name") == model_profile:
                return p
        return AiConfigProfile.get_active()

    async def _call_llm_safe(
        self, profile: dict, prompt: str, user: dict, timeout: float = 60.0
    ) -> dict:
        """LLM 安全调用（超时 + 降级，不抛异常）。

        Args:
            profile: AiConfigProfile 字典。
            prompt: 调用提示词。
            user: 当前用户字典（缺失兜底 ``{"id": 1}``，与 _run_root_cause 一致）。
            timeout: 单次调用超时秒数（默认 60s）。

        Returns:
            ``{"content": str, "used": bool, "error": Optional[str]}``。
        """
        from app.services.agent_llm import AgentLLM
        try:
            llm = AgentLLM(profile)
            resp = await asyncio.wait_for(
                llm.call(prompt, user=user or {"id": 1}),
                timeout=timeout,
            )
            if not resp.get("degraded") and resp.get("content"):
                return {"content": resp["content"], "used": True, "error": None}
            return {"content": "", "used": False, "error": resp.get("error") or "LLM 降级/无内容"}
        except asyncio.TimeoutError:
            return {"content": "", "used": False, "error": f"LLM 调用超时(>{timeout}s)"}
        except Exception as exc:
            logger.warning("PipelineEngine._call_llm_safe failed: %s", exc)
            return {"content": "", "used": False, "error": f"LLM 调用异常: {exc}"}

    def _tool_timeout(self, tool_id: str) -> float:
        """单工具超时：优先 tool 定义 timeout_ms，夹取 [5, 30] 秒。

        Args:
            tool_id: 工具业务主键。

        Returns:
            超时秒数（float，范围 [5, 30]）。
        """
        from app.models.mcp import McpTool
        try:
            tool = McpTool.get_by_id(tool_id)
            timeout_ms = int(tool.get("timeout_ms") or 30000) if tool else 30000
        except Exception:
            timeout_ms = 30000
        return max(5.0, min(30.0, timeout_ms / 1000.0))

    async def _run_tools_safe(self, tools: list, ctx: dict) -> dict:
        """执行 tools 列表中的每个工具，返回
        ``{"evidence": list, "tool_results": list, "errors": list[str], "used": bool}``。

        - 真实调用 ``ToolRegistry.call_tool``（``asyncio.to_thread`` 包裹，避免阻塞事件循环）；
        - 单工具超时夹取 [5, 30]s；
        - 任何失败只写 evidence/errors，**不阻断**其余工具。

        Args:
            tools: tool_id 列表。
            ctx: 执行上下文（含 host_id/event_id/input_params）。

        Returns:
            见上方结构；``used`` 表示是否有至少一个工具成功。
        """
        from app.services.mcp.registry import ToolRegistry
        evidence: list = []
        tool_results: list = []
        errors: list = []
        used = False
        input_params = ctx.get("input_params") or {}
        raw_tool_args = input_params.get("tool_args")
        explicit_args = raw_tool_args if isinstance(raw_tool_args, dict) else {}
        for tool_id in (tools or []):
            # 构造工具参数：显式 tool_args[tool_id] > 通用上下文（host_id/event_id）
            args = dict(explicit_args.get(tool_id) or {})
            args.setdefault("host_id", ctx.get("host_id"))
            args.setdefault("event_id", ctx.get("event_id"))
            tool_timeout = self._tool_timeout(tool_id)
            try:
                res = await asyncio.wait_for(
                    asyncio.to_thread(ToolRegistry.call_tool, tool_id, args),
                    timeout=tool_timeout,
                )
                if not isinstance(res, dict):
                    res = {"ok": False, "tool_id": tool_id, "error": "tool 返回非 dict"}
                tool_results.append(res)
                if res.get("ok"):
                    used = True
                    evidence.append({
                        "type": "tool_call", "ref": tool_id,
                        "status": "success",
                        "result": _truncate(res.get("result"), 2000),
                    })
                else:
                    evidence.append({
                        "type": "tool_call", "ref": tool_id,
                        "status": "failed", "error": res.get("error"),
                    })
                    errors.append(f"tool {tool_id}: {res.get('error')}")
            except asyncio.TimeoutError:
                evidence.append({"type": "tool_call", "ref": tool_id, "status": "failed", "error": "timeout"})
                errors.append(f"tool {tool_id}: 超时")
            except Exception as exc:  # 任何异常都不阻断
                logger.warning("PipelineEngine._run_tools_safe failed tool=%s: %s", tool_id, exc)
                evidence.append({"type": "tool_call", "ref": tool_id, "status": "failed", "error": str(exc)})
                errors.append(f"tool {tool_id}: {exc}")
        return {"evidence": evidence, "tool_results": tool_results, "errors": errors, "used": used}

    def _build_agent_prompt(
        self, agent_def: AgentDefinition, tool_results: list, data_sources: list
    ) -> str:
        """自动构造分析 prompt（无 input_params.prompt 时兜底）。

        Args:
            agent_def: Agent 定义。
            tool_results: 工具执行结果列表（每条含 ok/tool_id/result/error）。
            data_sources: 数据源名称列表。

        Returns:
            拼接后的 prompt 文本。
        """
        parts = ["你是一名应急响应分析师。请基于以下上下文对事件进行分析并给出结论。"]
        if agent_def.description:
            parts.append(f"智能体职责: {agent_def.description}")
        if data_sources:
            parts.append(f"数据源: {', '.join(data_sources)}")
        if tool_results:
            parts.append("工具执行结果:")
            for r in tool_results:
                rid = r.get("tool_id") if isinstance(r, dict) else ""
                if isinstance(r, dict) and r.get("ok"):
                    parts.append(f"- {rid}: {_truncate(r.get('result'), 500)}")
                else:
                    err = r.get("error") if isinstance(r, dict) else "未知错误"
                    parts.append(f"- {rid}: 执行失败({err})")
        else:
            parts.append("（无工具结果，请基于通用知识给出分析框架与建议）")
        parts.append("请用中文简洁回答。")
        return "\n".join(parts)

    async def _run_unknown(self, agent_def: AgentDefinition, ctx: dict) -> dict:
        """未知 custom Agent — 真实执行（P0）。

        行为矩阵：
        1) tools → ToolRegistry 真实调用，结果并入 evidence；
        2) model_profile → AgentLLM 真实生成分析结论（prompt 可引用工具结果）；
        3) 都无 → 原静态摘要兜底（向后兼容，输出形状与旧实现一致）。

        Args:
            agent_def: Agent 定义。
            ctx: 执行上下文。

        Returns:
            ``{stage, output, confidence, evidence, structured}`` 同构结果。
        """
        data_sources = agent_def.data_sources or []
        input_params = ctx.get("input_params") or {}
        context_vars = ctx.get("context_vars") or {}
        user = context_vars.get("user") or {}

        # 1) 工具执行
        tool_run = await self._run_tools_safe(agent_def.tools or [], ctx)
        evidence = list(tool_run["evidence"])
        errors = list(tool_run["errors"])

        # 2) LLM 生成结论（仅显式配置了 model_profile 才调，避免意外联网）
        output, confidence, used_llm = "", 0.5, False
        profile = self._resolve_llm_profile(agent_def.model_profile)
        if agent_def.model_profile and profile:
            prompt = input_params.get("prompt") or self._build_agent_prompt(
                agent_def, tool_run["tool_results"], data_sources
            )
            llm_res = await self._call_llm_safe(profile, prompt, user)
            if llm_res["used"]:
                output, confidence, used_llm = llm_res["content"], 0.8, True
            else:
                errors.append(llm_res["error"])

        # 3) 兜底：原静态摘要（保持旧输出形状）；有工具结果时输出工具摘要
        if not output:
            summary_parts = [f"# {agent_def.display_name}"]
            if data_sources:
                summary_parts.append(f"数据源: {', '.join(data_sources)}")
            summary_parts.append(f"依赖: {', '.join(agent_def.depends_on) if agent_def.depends_on else '无'}")
            if tool_run["used"]:
                summary_parts.append(f"工具执行: {len(tool_run['tool_results'])} 个工具已调用（详见证据）")
            if errors:
                summary_parts.append(f"执行提示: {'; '.join(errors[:5])}")
            output = "\n".join(summary_parts)

        return {
            "stage": agent_def.name,
            "output": output,
            "confidence": confidence,
            "evidence": evidence,
            "structured": {
                "summary": output[:160],
                "used_llm": used_llm,
                "used_tools": tool_run["used"],
                "model_profile": agent_def.model_profile,
                "tools": list(agent_def.tools or []),
                "errors": errors[:10],
                "tool_results": tool_run["tool_results"],
            },
        }

    async def _run_guardrail(self, ctx: dict, input_params: dict, mode: str) -> dict:
        """合规门禁（Guardrail）节点 — 记录 + 默认放行，显式 block 才阻断（P1-4）。

        委托 ``GuardrailAgent.evaluate``（独立类便于单测）；阻断时返回
        ``status="blocked"``，由 ``_execute_agent``/``_run_single`` 反映为
        stage failed，下游节点（拓扑序在后续 batch）不会执行。
        """
        from app.services.agents.guardrail_agent import GuardrailAgent
        return GuardrailAgent().evaluate(input_params)

    # ──────────────────────────────────────────────────────────────
    # 11 节点真实化：新增 9 个 runner + 公共助手（设计 A3.2-A3.11 / A5.1）
    # 统一签名 (ctx, input_params, mode) -> 同构 dict
    # ──────────────────────────────────────────────────────────────

    async def _run_hitl(self, ctx: dict, input_params: dict, mode: str) -> dict:
        """人工审核节点 — 返回 ``hitl_triggered=True`` + action/target，走现有审批链。

        触发条件（B3 共享知识 #6）：``agent_def.hitl == True AND result.hitl_triggered == True``。
        preset ``hitl`` 已置 ``hitl=True``；审批创建/等待/恢复全部复用 ``_run_single``
        既有 HITL 分支（``_create_hitl_approval`` → SSE ``hitl_waiting`` → resume 执行处置）。
        """
        action = input_params.get("action") or "export_report"
        target = input_params.get("target") or {}
        rollback = input_params.get("auto_rollback_plan") or {}
        reason = input_params.get("reason") or "人工审核节点"
        return {
            "stage": "hitl",
            "output": f"# 人工审核\n等待审批动作: {action}\n审批原因: {reason}",
            "confidence": 1.0,
            "evidence": [{"type": "hitl_request", "ref": f"action={action}", "target": target}],
            "structured": {
                "action": action,
                "target": target,
                "auto_rollback_plan": rollback,
                "reason": reason,
                "hitl_triggered": True,
            },
            "hitl_triggered": True,  # 关键：触发 _run_single 的 HITL 分支（L430）
        }

    async def _run_condition(self, ctx: dict, input_params: dict, mode: str) -> dict:
        """条件分支节点 — 输出控制信号方案（A2 决策 1，不物理剪枝）。

        对 ``input_params.conditions`` 逐条做表达式求值（JSONPath 子集 + 比较运算符），
        短路取首个命中分支；输出 ``branch_taken`` / ``condition_met`` / ``evaluations`` /
        ``downstream_active``。单条表达式异常只记 error，不阻断整节点。
        """
        conditions = input_params.get("conditions") or []
        evaluations: list = []
        branch_taken = None
        met = False
        for cond in conditions:
            cond = cond or {}
            expr = (cond.get("expr") or "").strip()
            ok, err = False, None
            try:
                ok = bool(self._eval_condition_expr(expr, ctx))
            except Exception as exc:  # noqa: BLE001 — 单条表达式异常 fail-safe
                ok, err = False, str(exc)
            evaluations.append({"label": cond.get("label"), "expr": expr, "result": ok, "error": err})
            if ok and branch_taken is None:
                branch_taken, met = cond.get("label"), True
        if not conditions:
            output = "# 条件分支\n未配置 conditions 表达式。"
            confidence = 0.5
        else:
            output = f"# 条件分支\n命中分支: {branch_taken or '（无命中）'}"
            confidence = 1.0 if met else 0.5
        downstream_active = (
            [b.get("target") for b in conditions if b.get("label") == branch_taken]
            if branch_taken is not None else []
        )
        return {
            "stage": "condition",
            "output": output,
            "confidence": confidence,
            "evidence": [{"type": "condition_eval", "branch_taken": branch_taken, "evaluations": evaluations}],
            "structured": {
                "branch_taken": branch_taken,
                "condition_met": met,
                "evaluations": evaluations,
                "downstream_active": downstream_active,
            },
        }

    async def _run_parallel(self, ctx: dict, input_params: dict, mode: str) -> dict:
        """并行分支节点 — 纯标记节点（A2 决策 2，零引擎改动）。

        输出分支列表 + ``parallel_mode``；下游节点只需声明 ``depends_on=[parallel 节点名]``，
        现有拓扑排序自然将其放入同一批并行执行。
        """
        branches = input_params.get("branches") or []
        branch_list = [
            {"label": b.get("label"), "target": b.get("target")}
            for b in branches if isinstance(b, dict)
        ]
        return {
            "stage": "parallel",
            "output": "# 并行分支\n下游节点声明依赖本节点后将并行执行。",
            "confidence": 1.0,
            "evidence": [{"type": "parallel_branches", "branches": branch_list}],
            "structured": {
                "branches": branch_list,
                "parallel_mode": "batch",
                "branch_count": len(branch_list),
            },
        }

    async def _run_data_process(self, ctx: dict, input_params: dict, mode: str) -> dict:
        """数据处理节点 — select/filter/rename/limit 操作链（A3.5）。

        ``source`` 为 ``{dep:<name>}.path`` 引用（缺省取全部前置 stage 输出拼接）；
        ``operations`` 按序执行，单条 op 异常只记 errors 继续后续 op（fail-safe）。
        """
        source = input_params.get("source") or ""
        operations = input_params.get("operations") or []
        # 1) 解析数据源
        if source:
            data = self._read_dep_output(ctx, source)
        else:
            data = {}
            for s in (ctx.get("stages") or []):
                out = self._stage_output(ctx.get("stages"), s.get("name"))
                if out:
                    data[s.get("name")] = out
        if data is None:
            data = []
        # 2) 顺序执行 operations
        transformed = data
        errors: list = []
        for op in operations:
            op = op or {}
            op_type = op.get("op")
            try:
                if op_type == "select":
                    fields = op.get("fields") or []
                    if isinstance(transformed, list):
                        transformed = [
                            {k: item.get(k) for k in fields if isinstance(item, dict) and k in item}
                            for item in transformed
                        ]
                    elif isinstance(transformed, dict):
                        transformed = {k: transformed[k] for k in fields if k in transformed}
                elif op_type == "filter":
                    field = op.get("field")
                    regex = op.get("regex")
                    if isinstance(transformed, list) and field and regex:
                        pattern = re.compile(str(regex))
                        transformed = [
                            item for item in transformed
                            if isinstance(item, dict) and pattern.search(str(item.get(field, "")))
                        ]
                elif op_type == "rename":
                    mapping = op.get("mapping") or {}
                    if isinstance(transformed, list):
                        renamed = []
                        for item in transformed:
                            if isinstance(item, dict):
                                renamed.append({mapping.get(k, k): v for k, v in item.items()})
                            else:
                                renamed.append(item)
                        transformed = renamed
                    elif isinstance(transformed, dict):
                        transformed = {mapping.get(k, k): v for k, v in transformed.items()}
                elif op_type == "limit":
                    n = int(op.get("n", 10) or 10)
                    if isinstance(transformed, list):
                        transformed = transformed[:n]
                    elif isinstance(transformed, dict):
                        transformed = dict(list(transformed.items())[:n])
                else:
                    errors.append(f"op '{op_type}' 未知")
            except Exception as exc:  # noqa: BLE001 — 单条 op 异常 fail-safe
                errors.append(f"op '{op_type}' 失败: {exc}")
        processed_count = (
            len(transformed) if isinstance(transformed, list)
            else (len(transformed) if isinstance(transformed, dict) else 0)
        )
        output = f"# 数据处理\n处理完成，产出 {processed_count} 条。"
        if errors:
            output += "\n部分操作失败: " + "; ".join(errors[:5])
        return {
            "stage": "data-process",
            "output": output,
            "confidence": 0.9,
            "evidence": [{
                "type": "data_process",
                "operations": [o.get("op") for o in operations if isinstance(o, dict)],
                "errors": errors[:10],
            }],
            "structured": {
                "transformed": transformed,
                "processed_count": processed_count,
                "errors": errors[:10],
            },
        }

    async def _run_intel_query(self, ctx: dict, input_params: dict, mode: str) -> dict:
        """外部情报查询节点 — 复用 EnrichmentService.enrich_ioc（A3.6）。

        仅支持 ip/domain（hash 友好报错）；真实外部 IO 一律 ``asyncio.to_thread`` +
        60s 超时包裹，任何异常返回 ``status="failed"`` + 可读 error，不抛 500。
        """
        ioc_type = (input_params.get("ioc_type") or "").lower()
        ioc_value = (input_params.get("ioc_value") or "").strip()
        provider_name = (input_params.get("provider_name") or "").strip() or None
        if ioc_type not in ("ip", "domain"):
            return {
                "stage": "intel-query",
                "status": "failed",
                "error": "unsupported_ioc_type",
                "output": "intel-query 仅支持 ip/domain（hash 请用 mcp-tool 或威胁情报节点）",
                "confidence": 0.0,
                "evidence": [],
                "structured": {"ioc_type": ioc_type, "ioc_value": ioc_value, "error": "unsupported_ioc_type"},
            }
        if not ioc_value:
            return {
                "stage": "intel-query",
                "status": "failed",
                "error": "missing_ioc_value",
                "output": "intel-query 缺少 ioc_value。",
                "confidence": 0.0,
                "evidence": [],
                "structured": {"ioc_type": ioc_type, "ioc_value": "", "error": "missing_ioc_value"},
            }
        from app.services.enrichment_service import EnrichmentService
        try:
            record = await asyncio.wait_for(
                asyncio.to_thread(
                    EnrichmentService.instance().enrich_ioc,
                    None, ioc_type, ioc_value, provider_name, False,
                ),
                timeout=60.0,
            )
        except Exception as exc:  # noqa: BLE001 — 配额/网络/无 provider → fail-safe
            logger.warning("PipelineEngine._run_intel_query failed %s/%s: %s", ioc_type, ioc_value, exc)
            return {
                "stage": "intel-query",
                "status": "failed",
                "error": f"intel_query_failed: {exc}",
                "output": f"外部情报查询失败：{exc}",
                "confidence": 0.0,
                "evidence": [],
                "structured": {"ioc_type": ioc_type, "ioc_value": ioc_value, "error": str(exc)},
            }
        record = record or {}
        return {
            "stage": "intel-query",
            "output": f"# 外部情报查询\n{ioc_type}: {ioc_value}\n威胁等级: {record.get('threat_level') or 'unknown'}",
            "confidence": 0.85 if record.get("risk_score") is not None else 0.5,
            "evidence": [{"type": "intel_query", "ref": ioc_value, "ioc_type": ioc_type, "provider": record.get("provider")}],
            "structured": {
                "record": record,
                "risk_score": record.get("risk_score"),
                "judgments": record.get("judgments"),
                "threat_level": record.get("threat_level"),
                "providers": record.get("providers"),
                "ioc_type": ioc_type,
                "ioc_value": ioc_value,
            },
        }

    async def _run_action(self, ctx: dict, input_params: dict, mode: str) -> dict:
        """处置执行节点 — 复用 ActionService.execute + disposition_service（A3.7）。

        默认直接执行（画布显式配置即授权）；``require_hitl=true`` 时返回
        ``hitl_triggered=True`` 走审批链（复用同一 HITL 分支）。写处置日志失败仅 warning。
        """
        action = input_params.get("action") or "export_report"
        target = input_params.get("target") or {}
        context_vars = ctx.get("context_vars") or {}
        operator = (
            input_params.get("operator")
            or (context_vars.get("user") or {}).get("username")
            or "admin"
        )
        if input_params.get("require_hitl"):
            return {
                "stage": "action",
                "hitl_triggered": True,
                "output": f"# 处置执行\n动作 {action} 需人工审批，等待审批链…",
                "confidence": 0.8,
                "evidence": [{"type": "action_hitl", "ref": f"action={action}", "target": target}],
                "structured": {
                    "action": action,
                    "target": target,
                    "mode": "hitl",
                    "require_hitl": True,
                    "operator": operator,
                },
                "hitl_triggered": True,
            }
        from app.services.action_service import ActionService
        try:
            ar = await ActionService.execute(action, target)
            executed = ar.model_dump() if hasattr(ar, "model_dump") else dict(ar)
        except Exception as exc:  # noqa: BLE001 — 执行器异常 → 不抛
            logger.warning("PipelineEngine._run_action execute failed %s: %s", action, exc)
            executed = {"success": False, "action": action, "error": str(exc)}
        event_id = ctx.get("event_id")
        if event_id:
            try:
                from app.services.disposition_service import add_disposition
                add_disposition(event_id=str(event_id), action=action,
                                operator=operator, comment="action 节点执行")
            except Exception as exc:  # noqa: BLE001 — 写日志失败仅 warning
                logger.warning("PipelineEngine._run_action add_disposition failed: %s", exc)
        return {
            "stage": "action",
            "output": f"# 处置执行\n动作 {action} 已执行：{'成功' if executed.get('success') else '失败'}",
            "confidence": 1.0 if executed.get("success") else 0.3,
            "evidence": [{"type": "action_executed", "ref": f"action={action}", "result": _truncate(executed, 2000)}],
            "structured": {
                "action": action,
                "target": target,
                "operator": operator,
                "executed": executed,
            },
        }

    async def _run_output(self, ctx: dict, input_params: dict, mode: str) -> dict:
        """知识库输出节点 — 复用 KnowledgeRetriever.retrieve（A3.8）。

        keyword 为空时用前置 stage 输出拼接生成查询文本（``_extract_keywords`` 兜底）；
        chroma/embedding 不可用由服务层自动关键词回退；任何异常返回空结果 + errors。
        """
        keyword = (input_params.get("keyword") or "").strip()
        category = (input_params.get("category") or "").strip()
        try:
            limit = max(1, int(input_params.get("limit", 5) or 5))
        except (ValueError, TypeError):
            limit = 5
        if not keyword:
            keyword = self._extract_keywords(ctx) or "安全事件分析"
        from app.services.knowledge_retriever import KnowledgeRetriever
        try:
            results = await asyncio.to_thread(
                KnowledgeRetriever.retrieve,
                {"summary": keyword, "category": category, "_raw_data": {}},
                limit,
                True,
            )
        except Exception as exc:  # noqa: BLE001 — 检索失败 fail-safe
            logger.warning("PipelineEngine._run_output retrieve failed: %s", exc)
            results = []
        items: list = []
        if isinstance(results, list):
            for r in results:
                items.append(r if isinstance(r, dict) else {"text": str(r)})
        return {
            "stage": "output",
            "output": f"# 知识库检索\n关键词: {keyword}\n命中 {len(items)} 条。",
            "confidence": 0.8 if items else 0.3,
            "evidence": [{"type": "knowledge_retrieve", "keyword": keyword, "count": len(items)}],
            "structured": {
                "keyword": keyword,
                "category": category,
                "limit": limit,
                "count": len(items),
                "items": items[:limit],
            },
        }

    async def _run_mcp_tool(self, ctx: dict, input_params: dict, mode: str) -> dict:
        """MCP 工具节点 — 复用 _run_tools_safe 单工具路径（A3.9）。

        ``input_params.args`` 注入 ``ctx.input_params.tool_args[tool_id]`` 透传给工具；
        工具未注册/超时 → evidence 记 failed + errors，**不阻断** node 本身。
        """
        tool_id = (input_params.get("tool_id") or "").strip()
        args = input_params.get("args") or {}
        if not tool_id:
            return {
                "stage": "mcp-tool",
                "status": "failed",
                "error": "missing_tool_id",
                "output": "mcp-tool 节点缺少 tool_id。",
                "confidence": 0.0,
                "evidence": [],
                "structured": {"tool_id": "", "args": args, "error": "missing_tool_id"},
            }
        # 注入 args → _run_tools_safe 读取的 ctx.input_params.tool_args[tool_id]
        tools_ctx = dict(ctx)
        tools_input = dict(ctx.get("input_params") or {})
        tool_args = dict(tools_input.get("tool_args") or {})
        tool_args[tool_id] = args
        tools_input["tool_args"] = tool_args
        tools_ctx["input_params"] = tools_input
        tool_run = await self._run_tools_safe([tool_id], tools_ctx)
        return {
            "stage": "mcp-tool",
            "output": f"# MCP 工具\n工具 {tool_id} 调用完成（{'成功' if tool_run['used'] else '失败'}）。",
            "confidence": 1.0 if tool_run["used"] else 0.3,
            "evidence": tool_run["evidence"],
            "structured": {
                "tool_id": tool_id,
                "args": args,
                "results": tool_run["tool_results"],
                "errors": tool_run["errors"][:10],
                "used": tool_run["used"],
            },
        }

    async def _run_intel_source(self, ctx: dict, input_params: dict, mode: str) -> dict:
        """情报源接入节点 — 只读 ThreatIntelProviderConfig.load()（A3.10）。

        过滤 enabled/provider，剔除 ``api_key_ref``（不泄露）；无外部 IO。
        """
        from app.models.threat_intel import ThreatIntelProviderConfig
        enabled_only = bool(input_params.get("enabled_only", True))
        provider_filter = (input_params.get("provider") or "").strip()
        try:
            configs = ThreatIntelProviderConfig.load()
        except Exception as exc:  # noqa: BLE001 — 配置缺失 fail-safe
            logger.warning("PipelineEngine._run_intel_source load failed: %s", exc)
            configs = []
        sources: list = []
        for c in (configs or []):
            if enabled_only and not c.get("enabled", True):
                continue
            if provider_filter and c.get("name") != provider_filter:
                continue
            sources.append({
                "name": c.get("name"),
                "type": c.get("type"),
                "base_url": c.get("base_url"),
                "enabled": bool(c.get("enabled", True)),
                "rate_limit_qps": c.get("rate_limit_qps"),
                "endpoints": c.get("endpoints") or {},
            })
        return {
            "stage": "intel-source",
            "output": f"# 情报源接入\n可用情报源 {len(sources)} 个。",
            "confidence": 1.0 if sources else 0.3,
            "evidence": [{"type": "intel_sources", "count": len(sources)}],
            "structured": {
                "sources": sources,
                "count": len(sources),
                "message": "未配置情报源。" if not sources else None,
            },
        }

    # ── 公共助手（A5.1 #4）──

    @staticmethod
    def _jsonpath_get(data: Any, path: str) -> Any:
        """点路径 + 整数索引解析：``a.b[0].c``（data-process/condition 共用）。

        遍历 dict 键与 list 索引；任一环缺失/越界返回 ``None``（不抛异常）。

        Args:
            data: 根对象（dict/list）。
            path: 点路径，支持 ``[n]`` 整数索引。

        Returns:
            路径解析结果；无法解析返回 ``None``。
        """
        if data is None or not path:
            return data
        current = data
        tokens = re.findall(r"[^.\[\]]+|\[\d+\]", path)
        for tok in tokens:
            if tok.startswith("[") and tok.endswith("]"):
                try:
                    idx = int(tok[1:-1])
                except ValueError:
                    return None
                if isinstance(current, list) and 0 <= idx < len(current):
                    current = current[idx]
                else:
                    return None
            else:
                if isinstance(current, dict) and tok in current:
                    current = current[tok]
                else:
                    return None
        return current

    def _read_dep_output(self, ctx: dict, dep_expr: str) -> Any:
        """解析 ``{dep:<agent_name>}`` 引用 → ``_stage_output`` 结果 + 点路径。

        兼容两种写法：``{dep:name}`` / ``{dep:name}.structured.used_llm`` / ``name.path``。

        Args:
            ctx: 执行上下文（含 ``stages``）。
            dep_expr: 依赖引用表达式。

        Returns:
            前置 stage 输出 dict 或路径解析结果；无法解析返回 ``None``。
        """
        dep_expr = (dep_expr or "").strip()
        match = re.match(r"^\{dep:([a-zA-Z0-9_\-]+)\}(.*)$", dep_expr)
        if match:
            name = match.group(1)
            path = match.group(2).lstrip(".")
        else:
            # 无 {dep:} 前缀时按整体作为 stage 名（兼容简单写法）
            parts = dep_expr.split(".", 1)
            name = parts[0]
            path = parts[1] if len(parts) > 1 else ""
        stages = ctx.get("stages") or []
        data = self._stage_output(stages, name)
        if path:
            return self._jsonpath_get(data, path)
        return data

    @staticmethod
    def _parse_literal(token: str) -> Any:
        """解析表达式字面量：字符串（单/双引号）、数字、``true/false/null``。

        Args:
            token: 待解析 token。

        Returns:
            解析后的 Python 值；无法识别按原字符串返回。
        """
        token = (token or "").strip()
        if token == "true":
            return True
        if token == "false":
            return False
        if token == "null":
            return None
        if len(token) >= 2 and token[0] == token[-1] and token[0] in ("'", '"'):
            return token[1:-1]
        try:
            return int(token)
        except (ValueError, TypeError):
            pass
        try:
            return float(token)
        except (ValueError, TypeError):
            pass
        return token

    def _eval_operand(self, token: str, ctx: dict) -> Any:
        """求值单个操作数：``{dep:name}.path`` 引用或字面量。

        Args:
            token: 操作数 token。
            ctx: 执行上下文。

        Returns:
            解析后的值；无法解析返回 ``None``。
        """
        token = (token or "").strip()
        if not token:
            return None
        if token.startswith("{dep:"):
            return self._read_dep_output(ctx, token)
        return self._parse_literal(token)

    def _eval_condition_expr(self, expr: str, ctx: dict) -> bool:
        """条件表达式求值（A5.2）：JSONPath 子集 + 比较运算符 + contains/exists/regex。

        支持语法：
        - 引用：``{dep:<agent_name>}.path``（``_read_dep_output`` 解析）；
        - 字面量：字符串（单/双引号）、数字、``true/false/null``；
        - 比较：``== != > < >= <=``（数值/相等比较）；
        - 集合：``lhs contains rhs``（子串/包含）、``path exists``（存在性）；
        - 正则：``lhs regex "pattern"``。
        非法表达式返回 ``False``，不抛异常（condition 节点 fail-safe 语义）。

        Args:
            expr: 表达式字符串。
            ctx: 执行上下文（含 ``stages``）。

        Returns:
            bool 求值结果。
        """
        expr = (expr or "").strip()
        if not expr:
            return False
        # 裸布尔字面量
        if expr in ("true", "false"):
            return expr == "true"
        if expr == "null":
            return False
        # regex 运算符：`lhs regex "pattern"`
        regex_match = re.match(r"^(.*?)\s+regex\s+(.+)$", expr)
        if regex_match:
            lhs = self._eval_operand(regex_match.group(1), ctx)
            pattern = self._parse_literal(regex_match.group(2).strip())
            if lhs is None:
                return False
            try:
                return re.search(str(pattern), str(lhs)) is not None
            except re.error:
                return False
        # exists 运算符：`path exists`
        exists_match = re.match(r"^(.*?)\s+exists$", expr)
        if exists_match:
            val = self._eval_operand(exists_match.group(1), ctx)
            return val is not None and val != "" and val != [] and val != {}
        # contains 运算符：`lhs contains rhs`
        contains_match = re.match(r"^(.*?)\s+contains\s+(.+)$", expr)
        if contains_match:
            lhs = self._eval_operand(contains_match.group(1), ctx)
            rhs = self._parse_literal(contains_match.group(2).strip())
            if isinstance(lhs, (list, dict, str)):
                try:
                    return rhs in lhs
                except TypeError:
                    return False
            return False
        # 比较运算符（先长后短）
        for op in (">=", "<=", "==", "!=", ">", "<"):
            if op in expr:
                left, right = expr.split(op, 1)
                lv = self._eval_operand(left.strip(), ctx)
                rv = self._parse_literal(right.strip())
                if op == "==":
                    return lv == rv
                if op == "!=":
                    return lv != rv
                try:
                    ln, rn = float(lv), float(rv)
                except (TypeError, ValueError):
                    return False
                if op == ">":
                    return ln > rn
                if op == "<":
                    return ln < rn
                if op == ">=":
                    return ln >= rn
                if op == "<=":
                    return ln <= rn
        # 兜底（BUG-3）：仅 {dep:...} 引用按存在性真值处理（A3.3 语义）；
        # 其余无运算符的非法表达式（如 "!!!" / "foo bar baz" / "1 + 2"）一律返回 False，
        # 避免垃圾表达式被 bool(字面量) 误判为 True 而错误命中 branch_taken。
        if expr.startswith("{dep:"):
            val = self._eval_operand(expr, ctx)
            return val is not None and val != "" and val != [] and val != {}
        return False

    def _extract_keywords(self, ctx: dict, max_len: int = 120) -> str:
        """从已完成 stage 输出中提取检索关键词（output 节点 keyword 兜底）。

        Args:
            ctx: 执行上下文。
            max_len: 关键词文本最大长度。

        Returns:
            拼接的关键词文本；无可用输出返回空字符串。
        """
        parts: list[str] = []
        for s in (ctx.get("stages") or []):
            raw = self._stage_output(ctx.get("stages"), s.get("name"))
            text = raw.get("output", "") if isinstance(raw, dict) else ""
            text = text or (raw.get("summary", "") if isinstance(raw, dict) else "")
            if text:
                parts.append(str(text)[:max_len])
        return " ".join(parts)[:max_len] if parts else ""

    async def _execute_agent(self, agent_def: AgentDefinition, run: PipelineRun) -> dict:
        """执行 Agent（模板方法，对接现有 Agent 子类或生成摘要）。

        对于 built-in 类型 Agent，从现有模块导入子类并调用 run()：
        - triage → TriageAgent
        - responder → ResponderAgent
        - reporter → ReporterAgent

        对于 7 个应急响应节点，委托 ``_run_<node>`` 执行（KC-1 解耦），
        host_id 优先取 ``run.ctx.host_id``，缺失按 ``event_id`` 反查。
        """
        name = agent_def.name

        # Built-in Agent 映射到现有实现
        if name == "triage":
            from app.services.agents.triage_agent import TriageAgent
            agent = TriageAgent()
            # P0-1.2: Agent.run() 设 120s 超时
            result = await asyncio.wait_for(agent.run(run.ctx, {}), timeout=120.0)
            return {
                "stage": "triage",
                "output": result.output,
                "confidence": result.confidence,
                "evidence": result.evidence,
                "usage": result.usage,
                "hitl_triggered": False,
            }
        elif name == "responder":
            from app.services.agents.responder_agent import ResponderAgent
            agent = ResponderAgent()
            # P0-1.2: Agent.run() 设 120s 超时
            result = await asyncio.wait_for(agent.run(run.ctx, {}), timeout=120.0)
            return {
                "stage": "response",
                "output": result.output,
                "confidence": result.confidence,
                "evidence": result.evidence,
                "usage": result.usage,
                "hitl_triggered": True,  # Responder 默认触发 HITL
            }
        elif name == "reporter":
            from app.services.agents.reporter_agent import ReporterAgent
            agent = ReporterAgent()
            # P0-1.2: Agent.run() 设 120s 超时
            result = await asyncio.wait_for(agent.run(run.ctx, {}), timeout=120.0)
            return {
                "stage": "report",
                "output": result.output,
                "confidence": result.confidence,
                "evidence": result.evidence,
                "usage": result.usage,
                "hitl_triggered": False,
            }
        else:
            # ── 应急响应专用 Agent — 委托 _run_<node> 执行（KC-1 解耦） ──
            host_id = run.ctx.get("host_id")
            if not host_id:
                host_id = self._resolve_host_id({"event_id": run.event_id})
                if host_id:
                    # 兼容整管 run：回写共享 ctx（仅整管路径，调试路径不写回）
                    run.ctx["host_id"] = host_id
            # P1-2: input_params 透传（节点配置 > run 级 ctx）
            input_params = {
                **(agent_def.config or {}).get("input_params", {}),
                **(run.ctx.get("input_params") or {}),
            }
            ctx = {
                "host_id": host_id,
                "event_id": run.event_id,
                "stages": run.stages,
                "input_params": input_params,
                "context_vars": run.ctx,
            }
            runner = self._get_node_runner(name)
            if runner is None:
                # 未知 custom Agent — 数据驱动摘要兜底
                result = await self._run_unknown(agent_def, ctx)
            else:
                result = await runner(ctx, input_params, "real")
            # P1-4: 透传节点显式状态（如 guardrail 阻断 status="blocked"），供 _run_single 判 failed
            node_status = result.get("status", "success")
            return {
                "stage": name,
                "output": result.get("output", ""),
                "confidence": result.get("confidence", 0.0),
                "evidence": result.get("evidence", []),
                "structured": result.get("structured", {}),  # P1-2: 保留节点结构化输出（prompt_used/query 等）
                "hitl_triggered": result.get("hitl_triggered", False),  # 11 节点：透传 hitl 标志（hitl/action(require_hitl)）
                "status": node_status,
                "error": result.get("error", "") if node_status != "success" else "",
            }

    # ── Stage 管理 ──

    def _stage_output(self, stages_or_run, name: str) -> dict:
        """读取指定 stage 的输出；未完成/未执行返回 ``{}``（P2-2 输出依赖防护）。

        接受 PipelineRun 实例或 stages 列表（``_run_<node>`` 仅持有 ctx.stages）。
        仅返回 ``status == "completed"`` 的 stage 输出，避免同批并发读到半成品。
        """
        stages = getattr(stages_or_run, "stages", None) or stages_or_run or []
        for s in stages:
            if s.get("name") == name and s.get("status") == "completed":
                out = s.get("output")
                if isinstance(out, dict):
                    return out
                if out is not None:
                    return {"output": out}
                return {}
        return {}

    def _stage_failed(self, run: PipelineRun, name: str) -> bool:
        """判断指定 stage 是否为失败/阻断/skipped 态（批间失败门控用，BUG-1）。

        - ``failed``：节点显式失败（如 guard 阻断、intel-query 查询失败）；
        - ``blocked``：guard 显式阻断（兼容直接落 stage 为 blocked 的场景）；
        - ``skipped``：依赖已失败被跳过的节点，其下游应传递跳过。

        Args:
            run: PipelineRun 实例。
            name: stage 名称。

        Returns:
            bool：该 stage 存在且处于失败/阻断/skipped 态。
        """
        for s in run.stages:
            if s.get("name") == name and s.get("status") in ("failed", "blocked", "skipped"):
                return True
        return False

    def _add_stage(
        self,
        run: PipelineRun,
        agent_name: str,
        status: str,
        elapsed: float = 0,
        cached: bool = False,
        output: Optional[dict] = None,
        error: str = "",
    ) -> None:
        """在 run 的 stages 中添加或更新一个 stage。"""
        existing = [s for s in run.stages if s["name"] == agent_name]
        if existing:
            existing[0].update({
                "status": status,
                "elapsed": elapsed,
                "cached": cached,
                "error": error,
            })
            if output:
                existing[0]["output"] = output
        else:
            run.stages.append({
                "name": agent_name,
                "status": status,
                "elapsed": elapsed,
                "cached": cached,
                "output": output or {},
                "error": error,
            })

    def _push_sse(
        self,
        run_id: str,
        event_type: str,
        data: dict,
        on_sse: Optional[Callable] = None,
    ) -> None:
        """推送 SSE 事件。"""
        if on_sse:
            # P2-5: 协程内异常可观测（logger.exception），不再静默吞
            asyncio.ensure_future(_safe_sse(on_sse, event_type, data))
        # 同时更新 run 中的 sse_events 缓存
        run = self._runs.get(run_id)
        if run:
            run.sse_events.append({"type": event_type, "data": data})

    # ── 生命周期管理 ──

    def cancel(self, run_id: str) -> bool:
        """取消正在执行的管道。

        P2-6：除置 cancelled 标志外，还唤醒 waiting_hitl 等待
        （``event.set(result=False)`` 使 ``_run_single`` 醒来标记 cancelled），
        并中断 in-flight 节点任务（``task.cancel()``）。

        Args:
            run_id: 运行 ID。

        Returns:
            bool: 是否成功取消（如管道已完成或不存在则返回 False）。
        """
        run = self._runs.get(run_id)
        if not run or run.status in ("completed", "cancelled", "failed"):
            return False
        run.cancelled = True
        run.status = "cancelled"
        run.completed_time = time.time()
        # P2-6: 唤醒 HITL 等待（result=False 让 _run_single 标记 cancelled）
        ev = self._hitl_events.get(run_id)
        if ev and not ev.is_set():
            ev.result = False  # type: ignore[attr-defined]
            ev.set()
        # P2-6: 中断 in-flight 节点任务
        for t in list(run.tasks):
            if not t.done():
                t.cancel()
        logger.info("PipelineEngine cancelled: run_id=%s", run_id)
        return True

    async def resume(self, run_id: str, approved: bool, user: dict) -> bool:
        """恢复 HITL 暂停的管道（DAG 路径）。

        - 内存中已有 Event → 直接唤醒（in-process 主路径）；
        - 内存无 Event 但 DB 是 waiting_hitl → 重建 Event 后唤醒（进程重启恢复）；
        - ``_runs`` 无该 run（孤儿）→ 调度 ``_continue_orphan_run`` 尽力续跑；
        - 其余情况返回 False。

        Args:
            run_id: 运行 ID。
            approved: 是否批准审批。
            user: 用户信息。

        Returns:
            bool: 是否成功恢复。
        """
        # P2-4: 首次调用时懒恢复 DB 中 waiting_hitl 事件
        self._ensure_restored()
        hitl_event = self._hitl_events.get(run_id)
        if hitl_event is None:
            run_record = AgentRun.get_by_run_id(run_id)
            if run_record and run_record.get("status") == "waiting_hitl":
                hitl_event = asyncio.Event()
                self._hitl_events[run_id] = hitl_event
                logger.info(
                    "Restored HITL event from DB for run_id=%s (process restart recovery)",
                    run_id,
                )
            else:
                logger.warning(
                    "HITL resume failed: run_id=%s not found or not waiting_hitl",
                    run_id,
                )
                return False

        # ── P0-3 核心：置位代码【移出】 if hitl_event is None 块 ──
        hitl_event.result = approved  # type: ignore[attr-defined]
        hitl_event.decided_by = (user or {}).get("id")  # type: ignore[attr-defined]
        hitl_event.set()

        run = self._runs.get(run_id)
        if run:
            # 防御：仅 waiting_hitl 状态恢复为 running（避免覆盖已完成状态）
            if run.status == "waiting_hitl":
                run.status = "running"
                try:
                    AgentRun.update(run_id, status="running")
                except Exception as exc:
                    logger.warning("PipelineEngine.resume: AgentRun.update(running) 失败: %s", exc)
            return True
        # 进程重启孤儿：内存 PipelineRun 已丢失，尽力从 DB 续跑剩余节点
        asyncio.create_task(self._continue_orphan_run(run_id, approved))
        return True

    # ── P0-3: 进程重启孤儿 run 的尽力续跑（best-effort，后台任务，异常不外抛）──
    async def _continue_orphan_run(self, run_id: str, approved: bool) -> None:
        """审批后内存 PipelineRun 已丢失时的续跑。

        从 ``agent_runs.ctx_json`` 还原 pipeline 定义，从 ``agent_run_steps``
        还原已完成节点；对 status=waiting_hitl 的节点直接以本次决议标记完成
        （避免重复触发 HITL / 重复审批），其余节点按拓扑序续跑，最终收敛到
        completed / failed / cancelled。任一步失败仅置 DB failed + 日志，
        不向 API 抛出（后台任务）。

        设计取舍：本路径为尽力而为；动作执行仍遵循「唯一执行点 = _run_single
        等待恢复后」原则，孤儿续跑不重复执行处置动作（记录 hitl_decision 即可）。
        """
        try:
            run_record = AgentRun.get_by_run_id(run_id)
            if not run_record:
                logger.warning("Orphan resume failed: run_id=%s 无记录", run_id)
                return
            ctx = _jl(run_record.get("ctx_json")) or {}
            agent_names = list(ctx.get("agent_names") or [])
            event_id = run_record.get("event_id") or ctx.get("event_id")
            user = ctx.get("user") or {}
            if not agent_names:
                logger.warning("Orphan resume failed: run_id=%s ctx 无 agent_names", run_id)
                AgentRun.update(run_id, status="failed",
                                result_json=json.dumps({"error": "orphan_resume_missing_agent_names"}, ensure_ascii=False))
                return
            # 对齐 run() 的 ensure_reporter 语义（custom 路径总是尾部补 reporter）
            if "reporter" not in agent_names:
                agent_names.append("reporter")

            # 从 agent_run_steps 还原：已完成节点 + waiting_hitl 节点 + 失败节点
            completed: set[str] = set()
            hitl_pending_nodes: list[str] = []
            failed_nodes: set[str] = set()
            for step in AgentRunStep.list_by_run(run_id):
                st = step.get("status")
                agent = step.get("agent") or step.get("stage")
                if not agent:
                    continue
                if st in ("success", "completed"):
                    completed.add(agent)
                elif st == "waiting_hitl":
                    hitl_pending_nodes.append(agent)
                elif st in ("failed", "blocked", "skipped"):
                    failed_nodes.add(agent)

            run = PipelineRun(run_id, agent_names, event_id, ctx)
            run.status = "running"
            self._runs[run_id] = run
            graph = self._registry.get_dependency_graph(agent_names)
            batches = self._topological_sort(graph)
            run.total_batches = len(batches)
            for batch_idx, batch in enumerate(batches):
                if run.cancelled:
                    break
                run.current_batch = batch_idx
                tasks = []
                for agent_name in batch:
                    if agent_name not in agent_names or agent_name in completed:
                        continue
                    # 11 节点真实化（BUG-1）：孤儿续跑同样做批间失败门控 —
                    # 依赖（DB 失败记录 或 本次续跑失败 stage）→ 标记 skipped 不执行
                    failed_deps = [
                        d for d in (graph.get(agent_name) or [])
                        if d in failed_nodes or self._stage_failed(run, d)
                    ]
                    if failed_deps:
                        self._add_stage(run, agent_name, "skipped",
                                        error=f"依赖 stage 失败/阻断: {', '.join(failed_deps)}")
                        try:
                            AgentRunStep.add(run_id=run_id, stage=agent_name, agent=agent_name,
                                             status="skipped",
                                             output_json={"error": f"dependency_failed: {', '.join(failed_deps)}"})
                        except Exception:
                            pass
                        failed_nodes.add(agent_name)
                        continue
                    if agent_name in hitl_pending_nodes:
                        # 本次决议即该节点的 HITL 决议（不重复触发审批门）
                        hitl_decision = {
                            "status": "approved" if approved else "rejected",
                            "resumed_by": "pipeline_engine_orphan",
                            "note": "orphan_resume_resolved_without_action",
                        }
                        self._add_stage(run, agent_name, "completed",
                                        output={"hitl_decision": hitl_decision,
                                                "note": "orphan_resume"})
                        try:
                            AgentRunStep.add(run_id=run_id, stage=agent_name, agent=agent_name,
                                             status="success",
                                             output_json={"hitl_decision": hitl_decision})
                        except Exception:
                            pass
                        completed.add(agent_name)
                        continue
                    task = asyncio.create_task(
                        self._run_single(agent_name, run, user, True, None)
                    )
                    run.tasks.add(task)
                    tasks.append(task)
                if not tasks:
                    continue
                await asyncio.gather(*tasks)
                for t in tasks:
                    run.tasks.discard(t)
            run.completed_time = time.time()
            final_status = compute_final_status(run)
            run.status = final_status
            AgentRun.update(
                run_id, status=final_status,
                result_json=json.dumps({"stages": run.stages, "agent_names": run.agent_names,
                                        "orphan_resume": True}, default=str, ensure_ascii=False),
            )
            logger.info("Orphan resume finished: run_id=%s status=%s", run_id, final_status)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Orphan resume failed: run_id=%s: %s", run_id, exc)
            try:
                AgentRun.update(run_id, status="failed",
                                result_json=json.dumps({"error": f"orphan_resume_failed: {exc}"}, ensure_ascii=False))
            except Exception:
                pass

    def get_status(self, run_id: str) -> Optional[dict]:
        """获取管道运行状态。

        Args:
            run_id: 运行 ID。

        Returns:
            状态字典，如不存在则返回 None。
        """
        run = self._runs.get(run_id)
        if not run:
            return None
        return {
            "run_id": run.run_id,
            "status": run.status,
            "current_batch": run.current_batch,
            "total_batches": run.total_batches,
            "stages": run.stages,
            "elapsed": round(time.time() - run.start_time, 1),
        }

    def get_run(self, run_id: str) -> Optional[PipelineRun]:
        """获取 PipelineRun 实例。

        Args:
            run_id: 运行 ID。

        Returns:
            PipelineRun 实例，如不存在则返回 None。
        """
        return self._runs.get(run_id)

    def cleanup(self, run_id: str) -> None:
        """清理运行资源。"""
        self._runs.pop(run_id, None)
        self._hitl_events.pop(run_id, None)

    # ── P2-4: 懒恢复（构造期不触 DB）──
    def _ensure_restored(self) -> None:
        """首次 run()/resume() 调用时恢复 DB 中 waiting_hitl 事件。

        模块导入期（``pipeline_engine = PipelineEngine()``）不再访问数据库；
        恢复失败仅记录日志，不阻断运行（运行时再尝试）。
        """
        if self._restored:
            return
        try:
            self._restore_hitl_events()
            # P2-3: 进程重启后残留的超龄 waiting_hitl 孤儿记录，一并兜底过期
            self._expire_orphan_waiting_hitl()
        except Exception as exc:
            logger.debug("PipelineEngine: 懒恢复失败（忽略，运行时再试）: %s", exc)
        finally:
            self._restored = True

    # ── P2-3: 孤儿 waiting_hitl 过期兜底（进程重启后 _runs 为空）──
    def _expire_orphan_waiting_hitl(self) -> int:
        """扫描 DB 中超龄 waiting_hitl 记录并置 expired + failed。

        进程重启后内存 ``_runs`` 为空，``_cleanup_expired_runs`` 的内存路径
        无法覆盖这些残留记录；在 ``_ensure_restored`` 时对 DB 做同等过期处理。
        """
        from app.models.agent_run import AgentRun
        try:
            data = AgentRun.list_all(status="waiting_hitl")
        except Exception as exc:
            logger.debug("PipelineEngine: 孤儿 waiting_hitl 扫描失败: %s", exc)
            return 0
        expired = 0
        for rec in (data.get("items") or []):
            run_id = rec.get("run_id")
            updated_at = rec.get("updated_at") or rec.get("created_at")
            if not updated_at:
                continue
            try:
                dt = datetime.strptime(str(updated_at), "%Y-%m-%d %H:%M:%S")
                age = time.time() - dt.replace(tzinfo=timezone.utc).timestamp()
            except (ValueError, TypeError):
                continue  # 无法解析时间 → 保守不处理
            if age <= self._HITL_EXPIRE_TTL:
                continue
            try:
                for ap in HitlApproval.list_by_run(run_id):
                    if ap.get("status") == HitlApproval.STATUS_PENDING:
                        HitlApproval.update_status(ap["id"], HitlApproval.STATUS_EXPIRED,
                                                   reason="审批超时未决议（清理）")
                AgentRun.update(run_id, status="failed",
                                result_json=json.dumps({"error": "hitl_expired_cleanup"}, ensure_ascii=False))
                expired += 1
            except Exception as exc:
                logger.warning("PipelineEngine: 孤儿 waiting_hitl 过期失败 run_id=%s: %s", run_id, exc)
        if expired:
            logger.info("PipelineEngine: 清理 %d 条孤儿 waiting_hitl 记录 (TTL=%.0fs)",
                        expired, self._HITL_EXPIRE_TTL)
        return expired

    # ── P1-1.4: 恢复 DB 中 waiting_hitl 的审批事件（进程重启后）──
    def _restore_hitl_events(self) -> int:
        """从 agent_runs 表扫描 status=waiting_hitl 的记录，重建 asyncio.Event。

        Returns:
            恢复的事件数。
        """
        from app.models.agent_run import AgentRun
        data = AgentRun.list_all(status="waiting_hitl")
        recovered = 0
        for run in (data.get("items") or []):
            run_id = run.get("run_id")
            if run_id and run_id not in self._hitl_events:
                self._hitl_events[run_id] = asyncio.Event()
                recovered += 1
        if recovered:
            logger.info(
                "PipelineEngine: 恢复 %d 个 waiting_hitl 审批事件（进程重启恢复）",
                recovered,
            )
        return recovered

    # ── P0-5.3: 定期清理过期的 _runs 记录，防止内存 OOM ──
    def _cleanup_expired_runs(self, ttl: Optional[float] = None) -> int:
        """清理超龄运行记录，释放内存。

        - ``completed / failed / cancelled``：超过 ``ttl``（默认 _CLEANUP_TTL=3600s）；
        - ``waiting_hitl``（P2-3）：超过 ``HITL_EXPIRE_TTL``（默认 24h）→
          相关 pending 审批置 expired + DB status=failed + 内存清理。

        Args:
            ttl: 过期秒数（默认 _CLEANUP_TTL = 3600s）。

        Returns:
            清理的记录数。
        """
        ttl = ttl or self._CLEANUP_TTL
        now = time.time()
        expired_ids = []
        for run_id, run in list(self._runs.items()):
            if run.status == "waiting_hitl":
                # P2-3: waiting_hitl 超 TTL → 审批 expired + DB failed + 内存清理
                if (now - run.start_time) > self._HITL_EXPIRE_TTL:
                    try:
                        for ap in HitlApproval.list_by_run(run_id):
                            if ap.get("status") == HitlApproval.STATUS_PENDING:
                                HitlApproval.update_status(ap["id"], HitlApproval.STATUS_EXPIRED,
                                                           reason="审批超时未决议（清理）")
                    except Exception as exc:
                        logger.warning("PipelineEngine: waiting_hitl 审批过期失败: %s", exc)
                    try:
                        AgentRun.update(run_id, status="failed",
                                        result_json=json.dumps({"error": "hitl_expired_cleanup"}, ensure_ascii=False))
                    except Exception as exc:
                        logger.warning("PipelineEngine: waiting_hitl DB 置 failed 失败: %s", exc)
                    expired_ids.append(run_id)
            elif run.status in ("completed", "failed", "cancelled"):
                completed = run.completed_time or (run.start_time + ttl)
                if (now - completed) > ttl:
                    expired_ids.append(run_id)
        for run_id in expired_ids:
            self._runs.pop(run_id, None)
            self._hitl_events.pop(run_id, None)
        if expired_ids:
            logger.info(
                "PipelineEngine: 清理 %d 条过期运行记录 (TTL=%.0fs)",
                len(expired_ids), ttl,
            )
        return len(expired_ids)


# 模块级单例
pipeline_engine = PipelineEngine()
