"""根因归因智能体（RootCauseAgent）— P1-G 根因归因（§4.3 / T-G1）.

职责：
- 复用 ``analysis/process_tree_builder.ProcessTreeBuilder`` 构建进程树；
- 读取 ``process_events`` / ``normalized_logs`` 真实数据；
- 沿 parent → child 回溯第一触发点（最早的、最可疑的进程事件），
  产出根因节点 + 因果链（root → 可疑子进程）；
- 优先用真实数据；``AgentLLM`` 仅用于自然语言解释，
  **降级时（degraded=True）仅给结构化链并标注"LLM 解释不可用"**。

作为 InvestigatorAgent 的子智能体被调用（investigator_agent 已懒加载本类）。
同时被 ``api/events.py`` 的 ``POST /analysis/root-cause`` 端点直接调用。

所有输出锚定真实数据域（process_events / security_events），禁止纯 LLM 编造。
"""

import logging
from typing import Any, Optional

from app.services.agents.base_agent import BaseAgent, AgentResult
from app.analysis.process_tree_builder import ProcessTreeBuilder
from app.services.agents import data_provider

logger = logging.getLogger(__name__)


class RootCauseAgent(BaseAgent):
    """根因归因智能体：进程树回溯第一触发点。"""

    name = "root_cause_agent"
    role = "根因归因"
    requires_hitl = False
    confidence_threshold = 0.7

    def __init__(self) -> None:
        super().__init__()
        # self._llm 由 BaseAgent.__init__ 统一实例化

    # ────────────────────────────────────────────────────────────────
    # 编排器 / Investigator 入口（返回 AgentResult）
    # ────────────────────────────────────────────────────────────────
    async def run(self, ctx: dict, task: dict) -> AgentResult:
        """执行根因归因，返回统一 AgentResult。"""
        detail = await self._analyze(ctx, task)
        result = AgentResult(
            stage="investigation",
            output=detail.get("summary", ""),
            confidence=detail.get("confidence", 0.0),
            evidence=detail.get("evidence", []),
        )
        self._apply_masking(result)
        return result

    # ────────────────────────────────────────────────────────────────
    # 端点入口（返回结构化明细）
    # ────────────────────────────────────────────────────────────────
    async def analyze(
        self,
        ctx: Optional[dict] = None,
        task: Optional[dict] = None,
        host_id: Optional[int] = None,
        event_id: Optional[str] = None,
        process_events: Optional[list] = None,
    ) -> dict:
        """执行根因归因，返回结构化明细（供 POST /analysis/root-cause 使用）。

        同时兼容两种调用约定：
        - 编排器 / InvestigatorAgent：``analyze(ctx, task)``
        - 端点：``analyze(host_id=..., event_id=..., ctx=...)``
        """
        ctx = ctx or {}
        task = task or {}
        if host_id is not None:
            task["host_id"] = host_id
        if event_id is not None:
            task["event_id"] = event_id
        if process_events is not None:
            task["process_events"] = process_events
        return await self._analyze(ctx, task)

    # ────────────────────────────────────────────────────────────────
    # 核心分析
    # ────────────────────────────────────────────────────────────────
    async def _analyze(self, ctx: dict, task: dict) -> dict:
        """根因回溯主逻辑。"""
        host_id = task.get("host_id") or ctx.get("host_id")
        event_id = task.get("event_id") or ctx.get("event_id")
        user = ctx.get("user")
        process_events = task.get("process_events") or []

        # 仅给定 event_id 时反查 host_id
        if not host_id and event_id:
            try:
                ev = data_provider.get_event(event_id)
                host_id = ev.get("host_id") if ev else None
            except Exception as exc:  # noqa: BLE001
                logger.debug("RootCauseAgent 反查 host 失败: %s", exc)

        # 读取进程事件（调用方未提供时从 DB 取）
        if not process_events and host_id:
            process_events = data_provider.get_process_events(host_id, limit=800)

        # 异常进程（用于进程树标记 + 触发点优选）
        abnormal = self._get_abnormal_processes(host_id) if host_id else []
        abnormal_pids = {a.get("pid") for a in abnormal if a.get("pid") is not None}
        pid_to_info: dict[int, dict] = {}
        for a in abnormal:
            pid = a.get("pid")
            if pid is None:
                continue
            pid_to_info[pid] = {
                "risk_score": a.get("risk_score", 0) or 0,
                "matched_rules": a.get("matched_rules"),
                "attack_path": a.get("attack_path"),
                "severity": a.get("severity"),
                "parent_name": a.get("parent_name"),
            }

        # 构建进程树（复用 ProcessTreeBuilder）
        tree_nodes = self._to_tree_nodes(process_events)
        process_tree = None
        try:
            process_tree = ProcessTreeBuilder.build(tree_nodes, abnormal_pids, pid_to_info, enrich=True)
        except Exception as exc:  # noqa: BLE001
            logger.debug("ProcessTreeBuilder 构建失败（跳过）: %s", exc)

        # 回溯第一触发点 + 因果链
        root_node, causal_chain = self._trace_root(process_events, abnormal_pids, pid_to_info)
        evidence = self._build_evidence(causal_chain)
        confidence = self._confidence(process_events, root_node, causal_chain)
        summary, llm_explanation = await self._explain(root_node, causal_chain, user)

        return {
            "host_id": host_id,
            "event_id": event_id,
            "root_node": root_node,
            "causal_chain": causal_chain,
            "confidence": confidence,
            "evidence": evidence,
            "summary": summary,
            "explanation": llm_explanation or summary,
            "degraded": llm_explanation is None,
            "process_tree": process_tree,
        }

    # ────────────────────────────────────────────────────────────────
    # 数据读取辅助
    # ────────────────────────────────────────────────────────────────
    @staticmethod
    def _get_abnormal_processes(host_id: int) -> list[dict]:
        """读取主机的异常进程（进程树标记用）。"""
        if not host_id:
            return []
        try:
            from app.database import get_connection

            with get_connection() as conn:
                rows = conn.execute(
                    "SELECT * FROM abnormal_processes WHERE host_id = ?",
                    (host_id,),
                ).fetchall()
            return [dict(r) for r in rows]
        except Exception as exc:  # noqa: BLE001
            logger.debug("读取异常进程失败（降级为空）: %s", exc)
            return []

    @staticmethod
    def _to_tree_nodes(process_events: list[dict]) -> list[dict]:
        """把 process_events 行映射为 ProcessTreeBuilder 所需的节点结构。"""
        nodes: list[dict] = []
        for p in process_events:
            if not isinstance(p, dict):
                continue
            nodes.append(
                {
                    "pid": p.get("pid"),
                    "ppid": p.get("ppid", 0) or 0,
                    "name": p.get("process_name") or "unknown",
                    "process_name": p.get("process_name") or "unknown",
                    "path": p.get("process_path") or "",
                    "command_line": p.get("command_line") or "",
                    "parent_name": p.get("parent_name") or "",
                    "event_time": p.get("event_time") or p.get("start_time") or "",
                    "start_time": p.get("start_time") or "",
                    "id": p.get("id"),
                    "host_id": p.get("host_id"),
                }
            )
        return nodes

    # ────────────────────────────────────────────────────────────────
    # 根因回溯
    # ────────────────────────────────────────────────────────────────
    def _trace_root(self, process_events: list[dict], abnormal_pids: set, pid_to_info: Optional[dict] = None) -> tuple:
        """回溯第一触发点（root_node）与因果链（root → 可疑子进程）。

        Returns:
            ``(root_node: dict|None, causal_chain: list[dict])``
        """
        if not process_events:
            return None, []

        pid_to_proc: dict[Any, dict] = {}
        for p in process_events:
            if not isinstance(p, dict):
                continue
            pid = p.get("pid")
            if pid is not None:
                pid_to_proc[pid] = p
        if not pid_to_proc:
            return None, []

        # 触发点：优先取异常进程中的最早者；否则取整体最早者
        candidates = [p for p in process_events if p.get("pid") in abnormal_pids] or list(process_events)
        trigger = min(candidates, key=lambda p: (p.get("event_time") or p.get("start_time") or "0"))

        # 沿 parent 向上回溯到根（ppid 不在集合或 ppid==0 即根）
        chain: list[dict] = []
        visited: set = set()
        cur = trigger
        while cur is not None:
            pid = cur.get("pid")
            if pid in visited:
                break
            visited.add(pid)
            chain.append(self._node_from_proc(cur, pid_to_info.get(cur.get("pid"))))
            ppid = cur.get("ppid", 0) or 0
            if ppid == 0 or ppid not in pid_to_proc:
                break
            cur = pid_to_proc.get(ppid)

        # chain 目前是 [trigger, parent, ..., root]；反转为 根 → 触发 的因果链
        causal_chain = list(reversed(chain))
        for i, node in enumerate(causal_chain):
            node["depth"] = i
        root_node = causal_chain[0] if causal_chain else None
        return root_node, causal_chain

    @staticmethod
    def _node_from_proc(p: dict, info: Optional[dict] = None) -> dict:
        """把一条进程事件转换为因果链节点。

        ``info`` 为 abnormal_processes 中该 pid 的画像（含 severity/attack_path/risk_score），
        用于标记节点是否异常。同时补充前端所需别名（parent_pid/start_time/evidence_ref）。
        """
        info = info or {}
        ppid = p.get("ppid", 0) or 0
        ts = p.get("event_time") or p.get("start_time") or ""
        ref = f"process_events.id={p.get('id')}"
        return {
            "pid": p.get("pid"),
            "ppid": ppid,
            "parent_pid": ppid,  # 前端别名
            "process_name": p.get("process_name") or "unknown",
            "parent_name": p.get("parent_name") or "",
            "command_line": p.get("command_line") or "",
            "event_type": p.get("event_type") or "",
            "time": ts,
            "start_time": ts,  # 前端别名
            "ref": ref,
            "evidence_ref": ref,  # 前端别名
            "host_id": p.get("host_id"),
            "is_abnormal": bool(
                info.get("severity") or info.get("attack_path") or info.get("risk_score")
            ),
            "severity": info.get("severity"),
            "attack_path": info.get("attack_path"),
        }

    @staticmethod
    def _build_evidence(causal_chain: list[dict]) -> list[dict]:
        """为因果链构造 evidence refs（指向 process_events 真实行）。"""
        evidence: list[dict] = []
        for node in causal_chain:
            ref = node.get("ref")
            if ref:
                evidence.append(
                    {
                        "type": "process_events",
                        "ref": ref,
                        "process_name": node.get("process_name"),
                        "pid": node.get("pid"),
                        "parent_name": node.get("parent_name"),
                    }
                )
        return evidence

    @staticmethod
    def _confidence(process_events: list[dict], root_node: Optional[dict], causal_chain: list[dict]) -> float:
        """基于数据丰富度估算置信度。"""
        confidence = 0.4
        if root_node:
            confidence += 0.2
        if len(causal_chain) > 1:
            confidence += 0.15
        if process_events:
            confidence += 0.1
        if any(c.get("event_type") for c in causal_chain):
            confidence += 0.1
        return round(min(confidence, 0.95), 2)

    # ────────────────────────────────────────────────────────────────
    # 自然语言解释（LLM 增强，降级不阻断）
    # ────────────────────────────────────────────────────────────────
    async def _explain(self, root_node: Optional[dict], causal_chain: list[dict], user: Optional[dict]) -> tuple:
        """构造数据驱动摘要；并尝试 LLM 自然语言解释。

        Returns:
            ``(summary: str, llm_explanation: str|None)``
        """
        if not root_node:
            summary = (
                "无进程事件数据，无法回溯第一触发点。"
                "建议确认该主机已采集进程事件（process_events）。"
            )
            return summary, None

        parts = [
            f"根因（第一触发点）：进程 {root_node.get('process_name')} "
            f"(pid={root_node.get('pid')}, 父进程={root_node.get('parent_name') or '无'}, "
            f"时间={root_node.get('time')}, {root_node.get('ref')})",
        ]
        if causal_chain:
            parts.append("因果链（根 → 可疑子进程）：")
            for i, node in enumerate(causal_chain, 1):
                parts.append(
                    f"  {i}. {node.get('process_name')} pid={node.get('pid')} "
                    f"ppid={node.get('ppid')} cmd={node.get('command_line')} ({node.get('ref')})"
                )
        summary = "\n".join(parts)

        # LLM 自然语言解释（仅增强；LLM 不可用时标注，不阻断）
        llm_explanation: Optional[str] = None
        try:
            prompt = self._build_llm_prompt(root_node, causal_chain)
            resp = await self._llm.call(prompt, user=user)
            if not resp.get("degraded") and resp.get("content"):
                llm_explanation = resp["content"]
        except Exception as exc:  # noqa: BLE001
            logger.debug("RootCauseAgent LLM 解释失败（跳过）: %s", exc)
        return summary, llm_explanation

    @staticmethod
    def _build_llm_prompt(root_node: dict, causal_chain: list[dict]) -> str:
        """构造 LLM 自然语言解释提示词。"""
        chain_text = "\n".join(
            f"- {n.get('process_name')} (pid={n.get('pid')}, ppid={n.get('ppid')}, "
            f"cmd={n.get('command_line')})"
            for n in causal_chain
        )
        return (
            "你是安全事件根因分析助手。以下是基于真实进程事件回溯出的因果链"
            "（数据来自 process_events，未做任何虚构）：\n\n"
            f"{chain_text}\n\n"
            "请用简洁中文解释这条因果链如何导致安全事件，指出最可能的最初触发点与"
            "可疑的子进程行为，并给出 1-2 条处置/取证建议（150 字以内）。"
            "严禁编造因果链中不存在的进程或 IP。"
        )

    # ────────────────────────────────────────────────────────────────
    # 脱敏
    # ────────────────────────────────────────────────────────────────
    @staticmethod
    def _apply_masking(result: AgentResult) -> None:
        """对 AgentResult 输出做 PII 脱敏（§8.6）。"""
        try:
            from app.services.data_masking import apply as mask_apply

            masked = mask_apply(result.to_dict())
            result.output = masked.get("output", result.output)
            result.evidence = masked.get("evidence", result.evidence)
        except Exception as exc:  # noqa: BLE001
            logger.debug("RootCauseAgent masking skipped: %s", exc)
