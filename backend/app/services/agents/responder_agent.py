"""处置智能体（ResponderAgent）— P0-A 多智能体闭环（§4.3 / T-A1 / §8.4）.

职责：
- 基于调查结论生成处置建议 + 经 Orchestrator 写 hitl_approvals（status=pending）。
- HITL 批准后再由本 Agent 经 ActionService 执行 + 写 event_disposition_log + 生成 auto_rollback_plan。
- **默认零自主**（requires_hitl=True）：任何真实动作都强制 HITL 审批。

降级要求：AgentLLM 返回 degraded=True 时，仍基于真实数据产出处置建议与回滚预案。
"""

import logging
from typing import Any, Optional

from app.shared.ai_constants import DEGRADED_MESSAGE_TEMPLATE
from app.services.agents.base_agent import BaseAgent, AgentResult
from app.services.agents import prompts
from app.services.agents import data_provider
from app.services.data_masking import apply as mask_apply

logger = logging.getLogger(__name__)


class ResponderAgent(BaseAgent):
    """处置智能体：生成可逆、低危的处置建议，强制 HITL。"""

    name = "responder_agent"
    role = "安全事件处置"
    requires_hitl = True  # 默认零自主，强制人工审批
    confidence_threshold = 0.7

    def __init__(self) -> None:
        super().__init__()

    async def run(self, ctx: dict, task: dict) -> AgentResult:
        """生成处置建议；写入 ctx['responder_action'] 供 HITL 网关使用。"""
        investigation = ctx.get("investigation", {}) or {}
        triage = ctx.get("triage", {}) or {}
        host_id = ctx.get("host_id")
        host = data_provider.get_host(host_id) if host_id else None
        logs = data_provider.get_logs_by_host(host_id, limit=200) if host_id else []
        sec_events = data_provider.get_security_events_by_host(host_id) if host_id else []

        # 数据驱动：推导建议动作 + 目标 + 回滚预案
        action, target, rollback = self._derive_action(host, logs, sec_events, investigation)

        recommendation = self._build_recommendation(action, target, rollback, host)
        llm_unavailable = False
        try:
            resp = await self._llm.call(
                prompts.build_responder_prompt(
                    investigation_result=investigation.get("summary", ""),
                    security_events_summary=data_provider.build_security_events_summary(sec_events),
                ),
                user=ctx.get("user"),
                trace_id=ctx.get("trace_id"),
            )
            if resp.get("degraded") or not resp.get("content"):
                llm_unavailable = True
            else:
                recommendation = resp["content"]
        except Exception as exc:  # noqa: BLE001
            logger.warning("ResponderAgent LLM 调用异常（降级）: %s", exc)
            llm_unavailable = True

        if llm_unavailable:
            recommendation = (
                f"{recommendation}\n\n"
                f"{DEGRADED_MESSAGE_TEMPLATE}"
            )

        # 写入上下文供 Orchestrator.wait_hitl 提取（dispatch 会从 ctx 读取）
        ctx["responder_action"] = {
            "action": action,
            "target": target,
            "auto_rollback_plan": rollback,
            "recommendation": recommendation,
        }

        evidence = investigation.get("evidence", []) or []
        # 动作目标作为补充证据
        evidence.append({
            "type": "responder_action",
            "ref": f"action={action}",
            "target": target,
        })

        confidence = float(triage.get("confidence", 0.5) or 0.5)

        result = AgentResult(
            stage="response",
            output=recommendation,
            confidence=confidence,
            evidence=evidence,
            hitl=True,  # 强制 HITL
        )
        self._apply_masking(result)
        return result

    # ── 动作推导（数据驱动，不编造目标）──
    @staticmethod
    def _derive_action(
        host: Optional[dict], logs: list[dict], sec_events: list[dict], investigation: dict
    ) -> tuple[str, dict, dict]:
        """基于真实数据推导建议动作 / 目标 / 回滚预案。

        Returns:
            (action, target, auto_rollback_plan)
        """
        # 1) 优先封禁可疑外连 IP（来自真实日志的 source_ip）
        suspicious_ips = []
        for log in logs:
            sev = log.get("severity")
            ip = log.get("source_ip")
            if ip and sev in ("high", "critical"):
                suspicious_ips.append(ip)
        # 也从 security_events 找网络外连
        for ev in sec_events:
            ev_type = ev.get("event_type", "")
            if ev_type == "network_outbound":
                mr = ev.get("matched_rules", "")
                suspicious_ips.append(f"security_event:{ev.get('id', '')} | rules={mr[:40]}")
        if suspicious_ips:
            # P2: 频次排序（取最可疑的 IP）
            if len(suspicious_ips) > 1:
                from collections import Counter
                ip_counter = Counter(suspicious_ips)
                ip = ip_counter.most_common(1)[0][0]
            else:
                ip = suspicious_ips[0]

            # P2: IP 白名单检查 — 跳过内网/保留地址
            _WHITELIST_PREFIXES = ("10.", "172.16.", "192.168.", "127.", "0.", "169.254.")
            if any(ip.startswith(prefix) for prefix in _WHITELIST_PREFIXES):
                # 白名单 IP 不执行封禁，降级为上报
                return (
                    "report_ip",
                    {"ip": ip, "reason": "白名单内网 IP，已跳过封禁"},
                    {"reversible": True, "plan": f"无需回滚（白名单 IP {ip} 仅上报未封禁）"},
                )

            return (
                "block_ip",
                {"ip": ip},
                {"reversible": True, "plan": f"在防火墙上删除对应封禁规则（撤销对 {ip} 的封锁）"},
            )

        # 2) 否则隔离失陷主机（来自真实主机画像）
        if host:
            hostname = host.get("hostname")
            return (
                "isolate_host",
                {"hostname": hostname, "host_id": host.get("id")},
                {"reversible": True, "plan": f"恢复主机 {hostname} 的网络连接（解除隔离）"},
            )

        # 3) 兜底：导出取证报告（天然可逆）
        return (
            "export_report",
            {"report_type": "incident"},
            {"reversible": True, "plan": "报告为只读产物，无需回滚"},
        )

    @staticmethod
    def _build_recommendation(
        action: str, target: dict, rollback: dict, host: Optional[dict]
    ) -> str:
        """构造数据驱动的处置建议文本。"""
        action_cn = {
            "block_ip": "封禁可疑外连 IP",
            "isolate_host": "隔离失陷主机",
            "export_report": "导出取证/处置报告",
            "report_ip": "上报可疑 IP（白名单跳过封禁）",
        }.get(action, action)
        lines = [
            f"建议处置动作：{action_cn}（action={action}）",
            f"动作目标（来自真实数据）：{target}",
            f"是否可逆：{rollback.get('reversible')}",
            f"自动回滚预案：{rollback.get('plan')}",
            "审批要求：本平台默认零自主，该动作需管理员 HITL 审批通过后执行。",
        ]
        if host:
            lines.insert(1, f"关联主机：{host.get('hostname')}（id={host.get('id')}）")
        return "\n".join(lines)

    # ── HITL 批准后的执行（由 Orchestrator.resume 调用）──
    async def execute_action(
        self, action: str, target: dict, event_id: Optional[str], operator: str
    ) -> tuple[dict, dict]:
        """经 ActionService 执行处置动作，并生成执行结果 + 回滚预案。

        Args:
            action: 动作名（block_ip / isolate_host / export_report）。
            target: 动作目标字典。
            event_id: 关联安全事件 ID（用于写 event_disposition_log）。
            operator: 执行人（审批人用户名）。

        Returns:
            (exec_result, auto_rollback_plan)
        """
        from app.services.action_service import ActionService
        from app.services.disposition_service import add_disposition

        rollback = self._rollback_for(action, target)
        exec_result: dict = {}
        try:
            ar = await ActionService.execute(action, target)
            exec_result = ar.model_dump() if hasattr(ar, "model_dump") else dict(ar)
        except Exception as exc:  # noqa: BLE001
            logger.error("ResponderAgent 执行动作 %s 失败: %s", action, exc)
            exec_result = {"success": False, "action": action, "error": str(exc)}

        # 写处置记录（event_disposition_log）
        if event_id:
            try:
                add_disposition(
                    event_id=str(event_id),
                    action=action,
                    operator=operator or "system",
                    comment=f"多智能体闭环自动处置（HITL 批准后执行）: {rollback.get('plan')}",
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("写 event_disposition_log 失败: %s", exc)

        return exec_result, rollback

    @staticmethod
    def _rollback_for(action: str, target: dict) -> dict:
        """返回动作的自动回滚预案（与 _derive_action 一致，供执行后回写）。"""
        plans = {
            "block_ip": f"在防火墙上删除对应封禁规则（撤销对 {target.get('ip')} 的封锁）",
            "isolate_host": f"恢复主机 {target.get('hostname')} 的网络连接（解除隔离）",
            "export_report": "报告为只读产物，无需回滚",
            "report_ip": "白名单 IP 仅上报未封禁，无需回滚",
        }
        return {"reversible": True, "plan": plans.get(action, "无回滚预案")}

    @staticmethod
    def _apply_masking(result: AgentResult) -> None:
        try:
            masked = mask_apply(result.to_dict())
            result.output = masked.get("output", result.output)
            result.evidence = masked.get("evidence", result.evidence)
        except Exception as exc:  # noqa: BLE001
            logger.debug("ResponderAgent masking skipped: %s", exc)
