"""管道并行执行引擎 — DAG 拓扑排序 + 分批并行 + SSE 推送 + HITL 暂停。

PipelineEngine 接收有序 Agent 名称列表，通过 AgentRegistry 获取依赖图，
Kahn 算法分层拓扑排序后逐批并行执行，每步通过 on_sse 回调解发 SSE 推送。
支持缓存查询（CacheManager）、人在回路暂停（HITL）、管道取消与状态查询。
"""

import asyncio
import json
import logging
import time
from collections import deque
from typing import Any, Callable, Optional

from app.models.agent_run import AgentRun, AgentRunStep
from app.services.agents.agent_definition import AgentDefinition
from app.services.agents.agent_registry import AgentRegistry
from app.services.agents.cache_manager import CacheManager, cache_manager

logger = logging.getLogger(__name__)


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

    async def _execute_agent(self, agent_def: AgentDefinition, run: PipelineRun) -> dict:
        """执行 Agent（模板方法，对接现有 Agent 子类或生成摘要）。

        对于 built-in 类型 Agent，从现有模块导入子类并调用 run()：
        - triage → TriageAgent
        - responder → ResponderAgent
        - reporter → ReporterAgent

        对于 custom 类型 Agent，返回数据驱动的摘要（待后续完善）。
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
            # ── 应急响应专用 Agent — 实打实的调查逻辑 ──
            host_id = run.ctx.get("host_id")
            # 如果 ctx 中没有 host_id，尝试从 security_events 查询
            if not host_id:
                try:
                    from app.database import get_connection
                    with get_connection() as conn:
                        row = conn.execute(
                            "SELECT host_id FROM security_events WHERE id = ? LIMIT 1",
                            (run.event_id.split(":")[-1] if ":" in run.event_id else run.event_id,),
                        ).fetchone()
                        if row:
                            host_id = row[0]
                            run.ctx["host_id"] = host_id
                except Exception:
                    pass

            if name == "file_analysis":
                """文件分析 — 查 security_events 中 file_create 事件，提取可疑文件名/路径。"""
                from app.services.agents.data_provider import get_security_events_by_host
                events = get_security_events_by_host(host_id) if host_id else []
                file_events = [e for e in events if e.get("event_type") == "file_create"]
                evidence_list = []
                lines = [f"# 文件分析报告\n"]
                if file_events:
                    lines.append(f"检测到 {len(file_events)} 条文件创建事件（命中规则）：")
                    for e in file_events[:15]:
                        ev = json.loads(e.get("evidence", "{}")) if isinstance(e.get("evidence"), str) else e.get("evidence", {})
                        fname = ev.get("file_name") or ev.get("path") or "未知文件"
                        fpath = ev.get("file_path") or ev.get("full_path") or ""
                        lines.append(f"\n  📄 {fname}")
                        if fpath:
                            lines.append(f"     路径: {fpath}")
                        mr = e.get("matched_rules", "")
                        if isinstance(mr, str) and len(mr) > 10:
                            try:
                                rules = json.loads(mr)
                                for r in rules[:2]:
                                    lines.append(f"     命中规则: {r.get('rule_name', '')}")
                            except:
                                lines.append(f"     命中规则: {mr[:80]}")
                        evidence_list.append({"type": "file_events", "ref": f"security_events.id={e['id']}", "file_name": fname})
                else:
                    lines.append("未检测到 file_create 类安全事件。")
                output = "\n".join(lines)
                return {
                    "stage": name, "output": output, "confidence": 0.75 if file_events else 0.3,
                    "evidence": evidence_list, "hitl_triggered": False,
                }

            elif name == "process_analysis":
                """进程分析 — 查 process_events 构建进程树，找出异常进程链。"""
                from app.services.agents.data_provider import get_connection
                procs = []
                if host_id:
                    with get_connection() as conn:
                        rows = conn.execute(
                            "SELECT id, process_name, process_path, command_line, pid, ppid, parent_name, start_time "
                            "FROM process_events WHERE host_id = ? ORDER BY start_time ASC LIMIT 200",
                            (host_id,),
                        ).fetchall()
                        procs = [dict(r) for r in rows]
                lines = [f"# 进程分析报告\n共记录 {len(procs)} 个进程事件。\n"]
                evidence_list = []
                if procs:
                    # 按 parent_name 分组构建进程树
                    tree = {}
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
                        if tree_items_shown >= 10: break
                        lines.append(f"\n  {parent} → {len(children)} 个子进程")
                        for c in children[:3]:
                            lines.append(f"      ├─ {c['process_name']} (PID={c['pid']})")
                            tree_items_shown += 1
                            evidence_list.append({"type": "process_events", "ref": f"process_events.id={c['id']}", "process_name": c["process_name"], "pid": c["pid"]})
                else:
                    # 兜底：process_events 表为空时，从 security_events 捞 process_start 事件
                    lines.append("process_events 表无数据，从 security_events 提取 process_start 事件：\n")
                    try:
                        from app.services.agents.data_provider import get_security_events_by_host
                        sec_events = get_security_events_by_host(host_id) if host_id else []
                        proc_events = [e for e in sec_events if e.get("event_type") == "process_start"]
                        if proc_events:
                            lines.append(f"检测到 {len(proc_events)} 条 process_start 事件（命中规则）：")
                            for e in proc_events[:12]:
                                ev = json.loads(e.get("evidence", "{}")) if isinstance(e.get("evidence"), str) else e.get("evidence", {})
                                pname = ev.get("process_name") or ev.get("exe") or "未知进程"
                                pid = ev.get("pid", ev.get("process_id", "?"))
                                lines.append(f"\n  🔵 {pname} (PID={pid})")
                                fpath = ev.get("process_path") or ev.get("image_path") or ""
                                if fpath:
                                    lines.append(f"     路径: {fpath}")
                                mr = e.get("matched_rules", "")
                                if isinstance(mr, str) and len(mr) > 10:
                                    try:
                                        rules = json.loads(mr)
                                        for r in rules[:1]:
                                            lines.append(f"     命中规则: {r.get('rule_name','')}")
                                    except: pass
                                evidence_list.append({"type": "security_events", "ref": f"security_events.id={e['id']}"})
                        else:
                            lines.append("security_events 中也无 process_start 事件。")
                    except Exception as exc:
                        lines.append(f"兜底查询失败: {exc}")
                    lines.append("无可用进程数据。")
                output = "\n".join(lines)
                return {
                    "stage": name, "output": output, "confidence": 0.7 if procs else 0.3,
                    "evidence": evidence_list, "hitl_triggered": False,
                }

            elif name == "network_analysis":
                """网络分析 — 查 network_connections 找出外联 IP、可疑连接。"""
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
                if conns:
                    # 找威胁连接
                    threat_conns = [c for c in conns if c.get("threat_level") in ("high", "critical")]
                    ext_conns = [c for c in conns if c.get("remote_addr") and not c["remote_addr"].startswith(("10.", "172.16.", "192.168.", "127."))]
                    lines.append(f"\n## 威胁连接: {len(threat_conns)} 条")
                    for c in threat_conns[:5]:
                        lines.append(f"  🔴 {c['local_addr']}:{c['local_port']} → {c['remote_addr']}:{c['remote_port']} ({c.get('protocol','?')})")
                        lines.append(f"     进程: {c.get('process_name','?')}  威胁: {c.get('threat_level','normal')}")
                        evidence_list.append({"type": "network_connection", "ref": f"network_connections.id={c['id']}", "local_addr": c.get("local_addr"), "remote_addr": c.get("remote_addr")})
                    lines.append(f"\n## 外网连接: {len(ext_conns)} 条")
                    for c in ext_conns[:5]:
                        if c.get("threat_level") in ("high", "critical"): continue
                        lines.append(f"  {c['local_addr']}:{c['local_port']} → {c['remote_addr']}:{c['remote_port']}")
                else:
                    lines.append("无网络连接数据。")
                output = "\n".join(lines)
                return {
                    "stage": name, "output": output, "confidence": 0.75 if conns and any(c.get("threat_level") in ("high", "critical") for c in conns) else 0.5,
                    "evidence": evidence_list, "hitl_triggered": False,
                }

            elif name == "registry_analysis":
                """注册表分析 — 查 security_events 中 persistence_register / registry_modify 事件。"""
                from app.services.agents.data_provider import get_security_events_by_host
                events = get_security_events_by_host(host_id) if host_id else []
                reg_events = [e for e in events if e.get("event_type") in ("persistence_register", "registry_modify")]
                lines = [f"# 注册表/持久化分析报告\n检测到 {len(reg_events)} 条注册表相关安全事件。\n"]
                evidence_list = []
                if reg_events:
                    by_rule = {}
                    for e in reg_events:
                        mr = e.get("matched_rules", "")
                        if isinstance(mr, str) and len(mr) > 10:
                            try:
                                rules = json.loads(mr)
                                for r in rules:
                                    rn = r.get("rule_name", "unknown")
                                    by_rule.setdefault(rn, []).append(e)
                            except:
                                by_rule.setdefault("unknown", []).append(e)
                    lines.append("\n## 按规则分组:")
                    for rule, evts in sorted(by_rule.items(), key=lambda x: -len(x[1]))[:8]:
                        lines.append(f"\n  ⚠️ {rule} — {len(evts)} 次命中")
                        for e in evts[:2]:
                            ev = json.loads(e.get("evidence", "{}")) if isinstance(e.get("evidence"), str) else e.get("evidence", {})
                            detail = ev.get("key") or ev.get("path") or ev.get("value") or ""
                            if detail:
                                lines.append(f"     详情: {detail[:120]}")
                            evidence_list.append({"type": "registry_events", "ref": f"security_events.id={e['id']}", "detail": detail[:60]})
                else:
                    lines.append("未检测到注册表/持久化类安全事件。")
                output = "\n".join(lines)
                return {
                    "stage": name, "output": output, "confidence": 0.8 if reg_events else 0.2,
                    "evidence": evidence_list, "hitl_triggered": False,
                }

            elif name == "timeline":
                """时间线重建 — 聚合所有数据源的时间点，构建攻击时间线。"""
                parts = [f"# 事件时间线\n"]
                timeline_data = []
                # 从 security_events 捞时间
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
                                except:
                                    pass
                            timeline_data.append((d["timestamp"], d["event_type"], d["severity"], rule_name))
                if timeline_data:
                    parts.append(f"共 {len(timeline_data)} 个时间节点：\n")
                    for ts, etype, sev, rname in timeline_data[:25]:
                        icon = "🔴" if sev == "high" else "🟡" if sev == "medium" else "⚪"
                        parts.append(f"  {icon} {ts}  [{sev}] {etype}")
                        if rname:
                            parts.append(f"     规则: {rname}")
                else:
                    parts.append("无可用的时间线数据。")
                output = "\n".join(parts)
                return {
                    "stage": name, "output": output, "confidence": 0.7 if timeline_data else 0.2,
                    "evidence": [], "hitl_triggered": False,
                }

            elif name == "root_cause":
                """根因定位 — 读取前面 Agent 的输出，用 LLM 综合分析识别第一触发点。"""
                # 搜集 ctx 中已有的分析结果（兼容 output 是 dict 或 str）
                prev_outputs = []
                for s in run.stages:
                    raw = s.get("output") or s.get("output_text") or {}
                    if isinstance(raw, dict):
                        text = raw.get("output", "") or raw.get("analysis", "") or ""
                    else:
                        text = str(raw)
                    if text:
                        prev_outputs.append(f"=== {s['name']} ===\n{text[:500]}")
                combined = "\n\n".join(prev_outputs) if prev_outputs else "无前置分析数据。"
                
                # 尝试调 LLM 做综合分析
                from app.services.agent_llm import AgentLLM
                from app.models.ai_config import AiConfigProfile
                profile = AiConfigProfile.get_active()
                result_text = combined
                confidence = 0.5
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
                    except Exception:
                        pass
                return {
                    "stage": name, "output": result_text, "confidence": confidence,
                    "evidence": [], "hitl_triggered": False,
                }

            elif name == "threat_intel":
                """威胁情报 — 查 IOC 匹配数据，关联外部威胁情报。"""
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
                if iocs:
                    lines.append("\n## IOC 匹配结果")
                    for ioc in iocs[:10]:
                        icon = "🔴" if ioc.get("severity") == "high" else "🟡"
                        lines.append(f"\n  {icon} {ioc['ioc_type']}: {ioc['ioc_value']}")
                        lines.append(f"     来源: {ioc.get('source','?')}  严重度: {ioc.get('severity','?')}")
                        if ioc.get("description"):
                            lines.append(f"     描述: {ioc['description'][:80]}")
                        evidence_list.append({"type": "ioc_hits", "ref": ioc["ioc_value"], "ioc_type": ioc.get("ioc_type")})
                else:
                    lines.append("未命中任何已知 IOC。")
                    # 也查 security_events 的 ioc_matches
                    from app.services.agents.data_provider import get_security_events_by_host
                    events = get_security_events_by_host(host_id) if host_id else []
                    for e in events:
                        ioc_match = e.get("ioc_matches")
                        if ioc_match:
                            lines.append(f"\n  security_events.id={e['id']} 含 IOC 匹配")
                            evidence_list.append({"type": "ioc_matches", "ref": f"security_events.id={e['id']}"})
                output = "\n".join(lines)
                return {
                    "stage": name, "output": output, "confidence": 0.8 if iocs else 0.3,
                    "evidence": evidence_list, "hitl_triggered": False,
                }

            else:
                # 未知 custom Agent — 数据驱动摘要兜底
                data_sources = agent_def.data_sources or []
                summary_parts = [f"# {agent_def.display_name}"]
                if data_sources:
                    summary_parts.append(f"数据源: {', '.join(data_sources)}")
                summary_parts.append(f"依赖: {', '.join(agent_def.depends_on) if agent_def.depends_on else '无'}")
                return {
                    "stage": name,
                    "output": "\n".join(summary_parts),
                    "confidence": 0.5,
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
