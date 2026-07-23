"""调查智能体（InvestigatorAgent）— P0-A 多智能体闭环（§4.3 / T-A1）.

职责：
- 拉取进程树 / 日志 / 主机画像 + cases（RAG 检索） → 攻击时间线 + 根因假设。
- 防御式懒导入调用 RootCauseAgent（该类在 T-G1 / 批次③ 实现）；
  缺失时跳过智能根因步骤并标注，保证本批可独立测试。

降级要求：AgentLLM 返回 degraded=True 时，仍基于真实数据
（process_events / normalized_logs / hosts）产出 evidence 充分的输出。
"""

import logging
from typing import Any, Optional

from app.shared.ai_constants import DEGRADED_MESSAGE_TEMPLATE
from app.services.agents.base_agent import BaseAgent, AgentResult
from app.services.agents import prompts
from app.services.agents import data_provider
from app.services.data_masking import apply as mask_apply

logger = logging.getLogger(__name__)


# 防御式懒导入 RootCauseAgent（批次③ 提供；缺失则为 None）
try:  # noqa: E402
    from app.services.agents.root_cause_agent import RootCauseAgent  # type: ignore
except ImportError:  # pragma: no cover - 批次③ 未实现时
    RootCauseAgent = None  # type: ignore


class InvestigatorAgent(BaseAgent):
    """调查智能体：还原攻击时间线、攻击手法与根因假设。"""

    name = "investigator_agent"
    role = "安全事件调查"
    requires_hitl = False
    confidence_threshold = 0.7

    def __init__(self) -> None:
        super().__init__()

    async def run(self, ctx: dict, task: dict) -> AgentResult:
        """执行调查。"""
        host_id = ctx.get("host_id") or task.get("host_id")
        if not host_id:
            # 尝试从事件推导
            eid = ctx.get("event_id") or (ctx.get("event_ids") or [None])[0]
            if eid:
                ev = data_provider.get_event(eid)
                host_id = ev.get("host_id") if ev else None
        host = data_provider.get_host(host_id) if host_id else None
        procs = data_provider.get_process_events(host_id, limit=500) if host_id else []
        logs = data_provider.get_logs_by_host(host_id, limit=200) if host_id else []

        # 时间线（进程事件 + 日志，按时间升序）
        timeline = self._build_timeline(procs, logs)
        # 根因假设（本地进程树回溯；若 RootCauseAgent 可用则增强）
        root_cause = self._local_root_cause(procs, logs)
        root_cause = await self._try_root_cause(host_id, procs, ctx, root_cause)

        # P0: 收集 security_events 统计数据
        event_ids = ctx.get("event_ids") or task.get("event_ids") or []
        if isinstance(event_ids, str):
            event_ids = [event_ids]
        security_events_count = 0
        if event_ids:
            security_events_count = len(event_ids)
        elif ctx.get("event_id"):
            security_events_count = 1

        evidence = data_provider.extract_process_refs(procs, 20) + data_provider.extract_log_refs(logs, 10)

        # RAG 检索历史案例（仅供参照，不阻断）
        rag_text = ""
        try:
            rag = data_provider.retrieve_cases(
                f"{ctx.get('triage', {}).get('summary', '')} {host.get('hostname', '') if host else ''}",
                limit=5,
            )
            if rag:
                rag_text = "\n".join(
                    r.get("formatted_text", r.get("title", "")) for r in rag[:5]
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Investigator RAG 检索失败（跳过）: %s", exc)

        data_summary = self._build_data_summary(host, timeline, root_cause, len(procs), len(logs), security_events_count)

        # 补充 security_events（仅命中规则的）
        sec_events = data_provider.get_security_events_by_host(host_id) if host_id else []

        llm_unavailable = False
        try:
            resp = await self._llm.call(
                prompts.build_investigator_prompt(
                    triage_result=ctx.get("triage", {}).get("summary", ""),
                    evidence=data_summary,
                    rag_cases=rag_text,
                    security_events_summary=data_provider.build_security_events_summary(sec_events),
                ),
                user=ctx.get("user"),
            )
            if resp.get("degraded") or not resp.get("content"):
                llm_unavailable = True
            else:
                output = resp["content"]
        except Exception as exc:  # noqa: BLE001
            logger.warning("InvestigatorAgent LLM 调用异常（降级）: %s", exc)
            llm_unavailable = True

        if llm_unavailable:
            output = (
                f"{data_summary}\n\n"
                f"{DEGRADED_MESSAGE_TEMPLATE}"
            )

        ctx["investigation"] = {
            "summary": output,
            "timeline": timeline,
            "root_cause": root_cause,
            "evidence": evidence,
        }

        # 置信度：随时间线与根因证据丰富度提升
        confidence = 0.4
        if procs:
            confidence += 0.25
        if timeline:
            confidence += 0.15
        if host:
            confidence += 0.1
        confidence = min(round(confidence, 2), 0.95)

        result = AgentResult(
            stage="investigation",
            output=output,
            confidence=confidence,
            evidence=evidence,
        )
        self._apply_masking(result)
        return result

    # ── 时间线 / 根因 ──
    @staticmethod
    def _build_timeline(procs: list[dict], logs: list[dict]) -> list[dict]:
        """构造攻击时间线（真实时间戳升序）。"""
        items: list[dict] = []
        for p in procs:
            ts = p.get("timestamp") or p.get("event_time") or p.get("start_time") or ""
            items.append({
                "time": ts,
                "kind": "process",
                "detail": f"{p.get('process_name')} (pid={p.get('pid')}, ppid={p.get('ppid')}, parent={p.get('parent_name')}) cmd={p.get('command_line')}",
                "ref": f"process_events.id={p.get('id')}",
            })
        for log in logs:
            items.append({
                "time": log.get("timestamp") or "",
                "kind": "log",
                "detail": f"{log.get('event_type')} sev={log.get('severity')} proc={log.get('process_name')} src={log.get('source_ip')}",
                "ref": f"normalized_logs.id={log.get('id')}",
            })
        items.sort(key=lambda x: x["time"] or "0")
        return items

    @staticmethod
    def _local_root_cause(procs: list[dict], logs: list[dict]) -> str:
        """基于进程树回溯的第一触发点（无 LLM 依赖）。"""
        if not procs:
            suspicious = [l for l in logs if (l.get("severity") in ("high", "critical"))]
            if suspicious:
                l = suspicious[0]
                return (
                    f"无进程事件可回溯；依据高严重度日志推断首个可疑点："
                    f"normalized_logs.id={l.get('id')}（{l.get('event_type')} / "
                    f"{l.get('process_name')} / src={l.get('source_ip')}）"
                )
            return "无进程事件与高严重度日志，无法推断第一触发点（建议补充采集）。"
        first = min(
            procs,
            key=lambda p: (p.get("timestamp") or p.get("event_time") or p.get("start_time") or "9"),
        )
        return (
            f"第一触发点（最早进程事件）：process_events.id={first.get('id')} "
            f"process={first.get('process_name')} pid={first.get('pid')} "
            f"parent={first.get('parent_name')} time={first.get('timestamp') or first.get('event_time') or first.get('start_time')}。"
            f"共回溯 {len(procs)} 条进程事件。"
        )

    async def _try_root_cause(
        self, host_id: Optional[int], procs: list[dict], ctx: dict, fallback: str
    ) -> str:
        """若 RootCauseAgent 可用则增强根因；否则返回 fallback。

        RootCauseAgent.run 为 async（与 BaseAgent 契约一致），此处 await 调用，
        并把其 AgentResult.output 并入调查报告，真正实现批次③要求的智能体集成。
        """
        if RootCauseAgent is None:
            return fallback + "\n（根因归因智能体 RootCauseAgent 尚未启用，已采用进程树初步回溯）"
        try:
            agent = RootCauseAgent()
            rc = await agent.run(
                ctx,
                {
                    "host_id": host_id,
                    "process_events": procs,
                    "event_id": ctx.get("event_id"),
                },
            )
            rc_dict = rc.to_dict()
            extra = rc_dict.get("output") or ""
            if extra:
                return fallback + "\n\n[RootCauseAgent 增强]\n" + str(extra)
        except Exception as exc:  # noqa: BLE001
            logger.warning("RootCauseAgent 调用失败（降级本地回溯）: %s", exc)
        return fallback

    @staticmethod
    def _build_data_summary(
        host: Optional[dict], timeline: list[dict], root_cause: str,
        proc_count: int, log_count: int, security_events_count: int = 0
    ) -> str:
        """构造数据驱动的调查概要。"""
        lines = []
        if host:
            lines.append(
                f"主机画像：{host.get('hostname')}（id={host.get('id')}, "
                f"ip={host.get('ip_address')}, os={host.get('os_type')} {host.get('os_version')}）"
            )
        lines.append(f"关联安全事件条数：{security_events_count}")
        lines.append(f"进程事件条数：{proc_count}")
        lines.append(f"范式化日志条数：{log_count}")
        lines.append(f"时间线条数：{len(timeline)}")
        if timeline:
            lines.append("时间线（前 10 条）：")
            for t in timeline[:10]:
                lines.append(f"  - [{t['time']}] {t['kind']}: {t['detail']} ({t['ref']})")
        lines.append("根因假设：")
        lines.append("  " + root_cause)
        return "\n".join(lines)

    @staticmethod
    def _apply_masking(result: AgentResult) -> None:
        try:
            masked = mask_apply(result.to_dict())
            result.output = masked.get("output", result.output)
            result.evidence = masked.get("evidence", result.evidence)
        except Exception as exc:  # noqa: BLE001
            logger.debug("InvestigatorAgent masking skipped: %s", exc)

    @staticmethod
    def _build_security_events_summary(events: list[dict]) -> str:
        """构建 security_events 的摘要文本，供 LLM 分析。

        按 event_type 分组计数，统计严重度分布，提取关键事件。
        """
        if not events:
            return ""
        from collections import Counter
        by_type: Counter[str] = Counter()
        high_sev = sum(1 for e in events if e.get("severity") == "high")
        medium_sev = sum(1 for e in events if e.get("severity") == "medium")
        matched = sum(1 for e in events if e.get("matched_rules"))
        parts = [f"共 {len(events)} 条命中规则的安全事件（High={high_sev}, Medium={medium_sev}）"]
        for e in events:
            by_type[e.get("event_type", "unknown")] += 1
        parts.append("按类型分布：")
        for t, c in by_type.most_common():
            parts.append(f"  - {t}: {c}条")
        key_events = [e for e in events if e.get("severity") == "high"]
        if key_events:
            parts.append(f"\n关键事件（High 严重度，{len(key_events)} 条）：")
            for e in key_events[:5]:
                parts.append(f"  [{e.get('event_type')}] rules={e.get('matched_rules','')}")
        return "\n".join(parts)
