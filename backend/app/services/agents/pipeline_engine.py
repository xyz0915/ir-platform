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
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from app.models.agent_run import AgentRun, AgentRunStep, NodeRunRepository
from app.services.agents.agent_definition import AgentDefinition
from app.services.agents.agent_registry import AgentRegistry
from app.services.agents.cache_manager import CacheManager, cache_manager
from app.services.agents.node_fixtures import get_fixture

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


class PipelineEngine:
    """管道执行引擎：DAG 解析 + 分批并行 + SSE 推送 + HITL 暂停。"""

    def __init__(self, max_concurrent: int = 5) -> None:
        self._registry = AgentRegistry()
        self._cache = cache_manager
        self._runs: dict[str, PipelineRun] = {}
        self._hitl_events: dict[str, asyncio.Event] = {}  # run_id → approval Event
        self._max_concurrent = max_concurrent

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
            on_sse: SSE 回调函数，每次状态变更时调用。

        Returns:
            {"run_id", "status", "stages", "total_elapsed", "results"}
        """
        run = PipelineRun(run_id, agent_names, event_id, ctx)
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
        graph = self._registry.get_dependency_graph(agent_names)
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
            # 并行执行 batch 内所有 Agent
            tasks = []
            for agent_name in batch:
                if agent_name not in agent_names:
                    continue
                tasks.append(self._run_single(agent_name, run, user, use_cache, on_sse))
            await asyncio.gather(*tasks)

            self._push_sse(run_id, "batch_complete", {"batch": batch_idx}, on_sse)
        # 4. 完成
        run.completed_time = time.time()
        if not run.cancelled:
            run.status = "completed"
        total_elapsed = round(run.completed_time - run.start_time, 1)
        # 持久化：最终状态
        try:
            final_status = "completed" if not run.cancelled else "cancelled"
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

        # 缓存检查
        cache_params = {"event_id": run.event_id, "agent": agent_name}
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
        # 实际执行
        try:
            result = await self._execute_agent(agent_def, run)
            elapsed = round(time.time() - start, 1)

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
                # 创建 HITL 审批事件（供 resume 恢复）
                hitl_event = asyncio.Event()
                self._hitl_events[run.run_id] = hitl_event
                return {"name": agent_name, "status": "waiting_hitl", "output": result}
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
        except Exception as exc:
            elapsed = round(time.time() - start, 1)
            error_msg = str(exc)
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
        """按节点类型映射内部 ``_run_<node>`` 执行体。"""
        return {
            "file_analysis": self._run_file_analysis,
            "process_analysis": self._run_process_analysis,
            "network_analysis": self._run_network_analysis,
            "registry_analysis": self._run_registry_analysis,
            "timeline": self._run_timeline,
            "root_cause": self._run_root_cause,
            "threat_intel": self._run_threat_intel,
            "branch": self._run_branch,
            "llm": self._run_llm,
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
        # 搜集 ctx 中已有的分析结果（兼容 output 是 dict 或 str）
        prev_outputs = []
        for s in (ctx.get("stages") or []):
            raw = s.get("output") or s.get("output_text") or {}
            if isinstance(raw, dict):
                text = raw.get("output", "") or raw.get("analysis", "") or ""
            else:
                text = str(raw)
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
        """自定义 LLM 节点 — 基于 prompt / model / input_params 合成分析结论。"""
        prompt = input_params.get("prompt") or ""
        model = input_params.get("model") or "gpt-4"
        query = input_params.get("query", "")
        summary = f"（自定义 LLM 节点）基于输入参数合成的结论：{query or '(未提供 query)'}"
        return {
            "stage": "llm",
            "output": f"# 自定义大模型节点\n{summary}",
            "confidence": 0.6,
            "evidence": [],
            "structured": {
                "summary": summary,
                "prompt_used": prompt,
                "model": model,
            },
        }

    async def _run_unknown(self, agent_def: AgentDefinition, ctx: dict) -> dict:
        """未知 custom Agent — 数据驱动摘要兜底。"""
        data_sources = agent_def.data_sources or []
        summary_parts = [f"# {agent_def.display_name}"]
        if data_sources:
            summary_parts.append(f"数据源: {', '.join(data_sources)}")
        summary_parts.append(f"依赖: {', '.join(agent_def.depends_on) if agent_def.depends_on else '无'}")
        output = "\n".join(summary_parts)
        return {
            "stage": agent_def.name,
            "output": output,
            "confidence": 0.5,
            "evidence": [],
            "structured": {"summary": output},
        }

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
            result = await agent.run(run.ctx, {})
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
            result = await agent.run(run.ctx, {})
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
            result = await agent.run(run.ctx, {})
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
            ctx = {
                "host_id": host_id,
                "event_id": run.event_id,
                "stages": run.stages,
                "input_params": {},
                "context_vars": run.ctx,
            }
            runner = self._get_node_runner(name)
            if runner is None:
                # 未知 custom Agent — 数据驱动摘要兜底
                result = await self._run_unknown(agent_def, ctx)
            else:
                result = await runner(ctx, {}, "real")
            return {
                "stage": name,
                "output": result.get("output", ""),
                "confidence": result.get("confidence", 0.0),
                "evidence": result.get("evidence", []),
                "hitl_triggered": False,
            }

    # ── Stage 管理 ──

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
            try:
                asyncio.ensure_future(on_sse(event_type, data))
            except Exception:
                pass
        # 同时更新 run 中的 sse_events 缓存
        run = self._runs.get(run_id)
        if run:
            run.sse_events.append({"type": event_type, "data": data})

    # ── 生命周期管理 ──

    def cancel(self, run_id: str) -> bool:
        """取消正在执行的管道。

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
        logger.info("PipelineEngine cancelled: run_id=%s", run_id)
        return True

    async def resume(self, run_id: str, approved: bool, user: dict) -> bool:
        """恢复 HITL 暂停的管道。

        Args:
            run_id: 运行 ID。
            approved: 是否批准审批。
            user: 用户信息。

        Returns:
            bool: 是否成功恢复。
        """
        hitl_event = self._hitl_events.get(run_id)
        if hitl_event:
            # 标记审批结果
            hitl_event.result = approved  # type: ignore[attr-defined]
            hitl_event.set()
            # 更新 run 状态
            run = self._runs.get(run_id)
            if run:
                run.status = "running"
            return True
        return False

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


# 模块级单例
pipeline_engine = PipelineEngine()
