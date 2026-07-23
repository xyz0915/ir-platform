"""分诊智能体（TriageAgent）— P0-A 多智能体闭环（§4.3 / T-A1）.

职责：
- 读取 security_events（含 ai_verdict）+ 命中规则参考 + normalized_logs。
- 聚类 / 定级 / 初步归因，产出事件包 {priority, confidence, evidence, summary}。
- 默认无需 HITL（requires_hitl=False）。

降级要求（§工程约束）：AgentLLM 返回 degraded=True 时，仍基于真实数据
（security_events / normalized_logs / rules）产出 evidence 充分的输出，
confidence 由数据驱动，并在 output 标注"LLM 摘要不可用"。绝不抛 500。
"""

import logging
from typing import Any, Optional

from app.shared.ai_constants import DEGRADED_MESSAGE_TEMPLATE
from app.services.agents.base_agent import BaseAgent, AgentResult
from app.services.agents import prompts
from app.services.agents import data_provider
from app.services.data_masking import apply as mask_apply

logger = logging.getLogger(__name__)


# severity → 优先级 / 排序权重
_SEVERITY_TO_PRIORITY = {
    "critical": "P0",
    "P0": "P0",
    "high": "P1",
    "P1": "P1",
    "medium": "P2",
    "P2": "P2",
    "low": "P3",
    "P3": "P3",
    "info": "P3",
}
_PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


class TriageAgent(BaseAgent):
    """分诊智能体：快速研判事件优先级与初步归因。"""

    name = "triage_agent"
    role = "安全事件分诊"
    requires_hitl = False
    confidence_threshold = 0.7

    def __init__(self) -> None:
        super().__init__()
        # 本次 LLM 调用统计（在 run 期间累加，最终写入 result）
        self._llm_calls_count: int = 0
        self._llm_usage: dict = {}
        self._llm_duration_ms: float = 0.0

    # ── 主入口 ──
    async def run(self, ctx: dict, task: dict) -> AgentResult:
        """执行分诊。

        Args:
            ctx: 运行上下文（event_id / event_ids / user）。
            task: 任务参数（可携带 event_ids 覆盖）。

        Returns:
            AgentResult（stage=triage）。
        """
        event_ids = self._resolve_event_ids(ctx, task)
        events = data_provider.get_events(event_ids)
        if not events and ctx.get("event_id"):
            single = data_provider.get_event(ctx["event_id"])
            if single:
                events = [single]
        events = [e for e in events if e]
        if not events:
            return AgentResult(
                stage="triage",
                output="未找到关联的安全事件，无法执行分诊。请确认 event_id 有效。",
                confidence=0.0,
                evidence=[],
            )

        host_id = events[0].get("host_id")
        logs = data_provider.get_logs_by_host(host_id, limit=200) if host_id else []
        rules = data_provider.get_enabled_rules()
        rules_hit = data_provider.get_rules_hit_summary(events[0], rules)

        # 补充 security_events 数据（比 normalized_logs 更丰富的安全事件）
        sec_events = data_provider.get_security_events_by_host(host_id) if host_id else []
        sec_events_summary = data_provider.build_security_events_summary(sec_events)

        # 数据驱动：优先级 + 置信度
        priority, confidence = self._data_driven(events, logs)
        evidence = data_provider.extract_event_refs(events) + data_provider.extract_log_refs(logs, 20)

        data_summary = self._build_data_summary(events, logs, rules_hit, priority)
        llm_unavailable = False

        # 尝试 LLM 摘要（降级安全）
        try:
            resp = await self._llm.call(
                prompts.build_triage_prompt(
                    event_summary=data_summary,
                    logs=self._log_preview(logs),
                    rules_hit=rules_hit,
                    security_events_summary=sec_events_summary,
                ),
                user=ctx.get("user"),
            )
            if resp.get("degraded") or not resp.get("content"):
                llm_unavailable = True
            else:
                output = resp["content"]
                # 累加 LLM 调用统计信息（token 用量、调用次数、耗时）
                self._llm_calls_count += 1
                self._llm_usage = resp.get("usage", {}) or {}
                self._llm_duration_ms = resp.get("execution_duration_ms") or 0
        except Exception as exc:  # noqa: BLE001
            logger.warning("TriageAgent LLM 调用异常（降级）: %s", exc)
            llm_unavailable = True

        if llm_unavailable:
            output = data_summary + f"\n\n{DEGRADED_MESSAGE_TEMPLATE}"

        # P1-8: 当 host_id 为 None 时在 output 中加入提示
        if not host_id:
            missing_host_note = "\n\n注意：该事件缺少 host_id，无法获取关联范式化日志，分诊仅基于事件自身数据。"
            output += missing_host_note

        # 下游共享上下文
        ctx["host_id"] = host_id
        ctx["event_ids"] = [e.get("id") for e in events]
        ctx["triage"] = {
            "priority": priority,
            "confidence": confidence,
            "summary": output,
            "evidence": evidence,
        }

        result = AgentResult(
            stage="triage",
            output=output,
            confidence=confidence,
            evidence=evidence,
            usage=self._llm_usage,
            llm_calls_count=self._llm_calls_count,
            execution_duration_ms=self._llm_duration_ms,
        )
        # PII 脱敏（§8.6）
        self._apply_masking(result)
        return result

    # ── 辅助方法 ──
    @staticmethod
    def _resolve_event_ids(ctx: dict, task: dict) -> list[str]:
        """解析事件 ID 列表（优先 task，其次 ctx）。"""
        ids = task.get("event_ids") or ctx.get("event_ids") or []
        if isinstance(ids, str):
            ids = [ids]
        if not ids and ctx.get("event_id"):
            ids = [ctx["event_id"]]
        return [str(i) for i in ids if i]

    def _data_driven(self, events: list[dict], logs: list[dict]) -> tuple[str, float]:
        """数据驱动的优先级与置信度（不依赖 LLM）。"""
        priorities = []
        for e in events:
            sev = (e.get("severity") or "info")
            priorities.append(_SEVERITY_TO_PRIORITY.get(sev, "P2"))
        priority = min(priorities, key=lambda p: _PRIORITY_ORDER.get(p, 3))

        # ai_verdict 命中 suspicious → 提升一档
        try:
            for e in events:
                verdict = data_provider._json_loads(e.get("ai_verdict"), {}) or {}
                if verdict.get("label") == "suspicious":
                    if _PRIORITY_ORDER.get(priority, 3) > 1:
                        priority = "P1"
                    break
        except Exception:  # noqa: BLE001
            pass

        # 置信度：随证据丰富度提升
        confidence = 0.4
        if logs:
            confidence += 0.2
        if any((e.get("ai_verdict") for e in events)):
            confidence += 0.2
        if len(events) > 1:
            confidence += 0.1
        confidence = min(round(confidence, 2), 0.95)

        # P2 增强：多事件聚合效应
        if len(events) > 3:
            high_count = sum(1 for e in events if e.get("severity") in ("high", "critical"))
            if high_count >= len(events) * 0.6:
                priority = min(priority, 1) if isinstance(priority, int) else priority

        # P2 增强：时间聚集效应（多事件时间跨度 < 5 分钟 → 优先级提升一级）
        timestamps = []
        for e in events:
            ts = e.get("timestamp")
            if ts:
                timestamps.append(ts)
        if len(timestamps) > 1:
            try:
                from datetime import datetime
                parsed = []
                for t in timestamps:
                    if isinstance(t, str):
                        parsed.append(datetime.fromisoformat(t.replace("Z", "+00:00")))
                    elif isinstance(t, (int, float)):
                        from datetime import timezone
                        parsed.append(datetime.fromtimestamp(t, tz=timezone.utc))
                if len(parsed) > 1:
                    span = (max(parsed) - min(parsed)).total_seconds()
                    if span < 300:  # 5 分钟内
                        if isinstance(priority, str) and _PRIORITY_ORDER.get(priority, 3) > 0:
                            priority = [k for k, v in sorted(_PRIORITY_ORDER.items(), key=lambda x: x[1]) if v < _PRIORITY_ORDER[priority]][0] if any(v < _PRIORITY_ORDER[priority] for v in _PRIORITY_ORDER.values()) else priority
            except Exception:  # noqa: BLE001
                pass

        return priority, confidence

    @staticmethod
    def _build_data_summary(
        events: list[dict], logs: list[dict], rules_hit: str, priority: str
    ) -> str:
        """构造数据驱动的分诊概要（纯真实字段）。"""
        e0 = events[0]
        lines = [
            f"事件数量：{len(events)}",
            f"代表事件 ID：{e0.get('id')}",
            f"事件类型：{e0.get('event_type')}",
            f"最高严重度：{e0.get('severity')}",
            f"建议优先级：{priority}",
            f"主机 ID：{e0.get('host_id')}",
            f"时间戳：{e0.get('timestamp')}",
        ]
        try:
            verdict = data_provider._json_loads(e0.get("ai_verdict"), {}) or {}
            if verdict:
                lines.append(f"AI 初判：{verdict.get('label', 'unknown')}（{verdict.get('reason', '')}）")
        except Exception:  # noqa: BLE001
            pass
        if rules_hit:
            lines.append(f"命中规则参考：{rules_hit}")
        if logs:
            lines.append(f"相关范式化日志条数：{len(logs)}")
        return "\n".join(lines)

    @staticmethod
    def _build_security_events_summary(events: list[dict]) -> str:
        """构建 security_events 的摘要文本，供 LLM 分析。

        按 event_type 分组计数，并提取关键证据。
        """
        if not events:
            return ""
        from collections import Counter
        by_type: Counter[str] = Counter()
        # 同时也统计不同严重度的分布
        high_sev = sum(1 for e in events if e.get('severity') == 'high')
        medium_sev = sum(1 for e in events if e.get('severity') == 'medium')
        matched = sum(1 for e in events if e.get('matched_rules'))

        parts = [f"共 {len(events)} 条安全事件（High={high_sev}, Medium={medium_sev}, 命中规则={matched}）"]

        for e in events:
            by_type[e.get('event_type', 'unknown')] += 1

        parts.append("按类型分布：")
        for t, c in by_type.most_common():
            parts.append(f"  - {t}: {c}条")

        # 提取关键事件（命中规则或 high severity 的）
        key_events = [e for e in events if e.get('matched_rules') or e.get('severity') == 'high']
        if key_events:
            parts.append(f"\n关键事件（{len(key_events)} 条）：")
            for e in key_events[:5]:
                parts.append(f"  [{e.get('severity','')}] {e.get('event_type')} | rules={e.get('matched_rules','')}")

        return "\n".join(parts)

    @staticmethod
    def _log_preview(logs: list[dict], max_chars: int = 3000) -> str:
        """构造用于 LLM 的日志预览（脱敏由 data_masking 在输出层统一处理）。"""
        if not logs:
            return "（无相关范式化日志）"
        parts = []
        total = 0
        for log in logs[:30]:
            line = (
                f"[{log.get('timestamp')}] {log.get('event_type')} "
                f"sev={log.get('severity')} src={log.get('source_ip')} "
                f"proc={log.get('process_name')} cmd={log.get('command_line')}"
            )
            if total + len(line) > max_chars:
                break
            parts.append(line)
            total += len(line)
        return "\n".join(parts)

    @staticmethod
    def _apply_masking(result: AgentResult) -> None:
        """对输出与证据做 PII 脱敏（就地更新）。"""
        try:
            masked = mask_apply(result.to_dict())
            result.output = masked.get("output", result.output)
            result.evidence = masked.get("evidence", result.evidence)
        except Exception as exc:  # noqa: BLE001
            logger.debug("TriageAgent masking skipped: %s", exc)
