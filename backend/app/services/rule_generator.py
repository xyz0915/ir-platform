"""规则草稿生成器（P0-B）.

从 ``normalized_logs`` 样本或告警上下文，调用 :class:`AgentLLM` 归纳出候选检测规则。
若当前无可用 LLM（未配置 AI 画像 / 调用失败 / 熔断），自动降级为基于样本统计的
启发式规则生成，保证功能在离线环境下仍可演示与自测。
"""

import json
import logging
import re
from collections import Counter
from typing import Any, Dict, List, Optional

from app.services.agent_llm import AgentLLM
from app.services.rule_dsl import RuleDSL

logger = logging.getLogger(__name__)


class RuleGenerator:
    """规则生成器：LLM 为主，启发式降级兜底."""

    def __init__(self, llm: Optional[AgentLLM] = None):
        self._llm = llm or AgentLLM()

    async def generate(
        self,
        sample_logs: List[Dict[str, Any]],
        category: Optional[str] = None,
        user: Optional[dict] = None,
    ) -> Dict[str, Any]:
        """生成一条候选规则草稿.

        Returns:
            草稿字典：{name, rule_type, condition, severity, label, rationale,
                       expected_fields, confidence, source, dsl_error?}
        """
        prompt = self._build_prompt(sample_logs, category)
        result = await self._llm.call(prompt, user=user)
        if result.get("error") or result.get("degraded"):
            logger.info("LLM 不可用（%s），回退启发式规则生成", result.get("error"))
            draft = self._heuristic_generate(sample_logs, category)
        else:
            draft = self._parse_llm_response(result.get("content", ""), sample_logs, category)
        # DSL 安全校验：不通过时记录 dsl_error，但仍回传草稿供人工复核
        ok, err = RuleDSL.validate(draft["rule_type"], draft["condition"])
        if not ok:
            draft["dsl_error"] = err
            logger.warning("生成的规则未通过 DSL 校验: %s", err)
        return draft

    # ── 提示词构建 ───────────────────────────────────────────────────────
    def _build_prompt(self, sample_logs: List[Dict[str, Any]], category: Optional[str]) -> str:
        sample = sample_logs[:20]
        logs_json = json.dumps(sample, ensure_ascii=False, default=str)
        cat_hint = f"类别偏向：{category}。" if category else ""
        return (
            "你是一名安全检测规则工程师。请基于以下归一化日志样本，归纳出一条"
            "可计算、低风险、避免全表扫描的检测规则。\n"
            f"{cat_hint}"
            "只返回一个 JSON 对象，字段如下：\n"
            "{\n"
            '  "name": "英文规则键(唯一, snake_case)",\n'
            '  "rule_type": "regex|list|threshold|exists|behavior|composite",\n'
            '  "condition": { ... 合规的 condition 对象 ... },\n'
            '  "severity": "low|medium|high|critical",\n'
            '  "label": "中文展示名",\n'
            '  "rationale": "为什么这条规则能检测该威胁",\n'
            '  "expected_fields": ["命中的字段"],\n'
            '  "confidence": 0.0~1.0\n'
            "}\n"
            "注意：condition 只能使用白名单字段(event_type/process_name/source_ip/"
            "user_name 等)，禁止 eval/exec/SQL/DDL，禁止正则 '.*' 全匹配。\n"
            f"样本日志：\n{logs_json}\n"
        )

    # ── LLM 响应解析 ─────────────────────────────────────────────────────
    def _parse_llm_response(
        self, content: str, sample_logs: List[Dict[str, Any]], category: Optional[str]
    ) -> Dict[str, Any]:
        try:
            start = content.find("{")
            end = content.rfind("}")
            if start == -1 or end == -1:
                raise ValueError("response has no json")
            obj = json.loads(content[start : end + 1])
            rule_type = obj.get("rule_type", "list")
            condition = obj.get("condition") or {}
            if not isinstance(condition, dict):
                condition = {}
            return {
                "name": self._safe_name(obj.get("name") or "ai_rule"),
                "rule_type": rule_type
                if rule_type
                in {"regex", "list", "threshold", "behavior", "composite", "exists"}
                else "list",
                "condition": condition,
                "severity": obj.get("severity", "medium"),
                "label": obj.get("label"),
                "rationale": obj.get("rationale"),
                "expected_fields": obj.get("expected_fields") or [],
                "confidence": float(obj.get("confidence", 0.5) or 0.5),
                "source": "ai",
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("解析 LLM 响应失败，回退启发式: %s", exc)
            return self._heuristic_generate(sample_logs, category)

    # ── 离线启发式生成 ────────────────────────────────────────────────────
    def _heuristic_generate(
        self, sample_logs: List[Dict[str, Any]], category: Optional[str]
    ) -> Dict[str, Any]:
        """基于样本统计生成规则：优先频繁进程名，其次频繁事件类型."""
        type_counter: Counter = Counter()
        proc_counter: Counter = Counter()
        for log in sample_logs:
            if not isinstance(log, dict):
                continue
            if log.get("event_type"):
                type_counter[str(log["event_type"])] += 1
            if log.get("process_name"):
                proc_counter[str(log["process_name"])] += 1

        if proc_counter:
            top_proc, cnt = proc_counter.most_common(1)[0]
            return {
                "name": self._safe_name(f"ai_proc_{top_proc}"),
                "rule_type": "list",
                "condition": {
                    "field": "process_name",
                    "values": [top_proc],
                    "match_mode": "exact",
                },
                "severity": "medium",
                "label": f"AI 归纳：进程 {top_proc} 频繁出现",
                "rationale": f"样本中进程 {top_proc} 出现 {cnt} 次，可能为可疑活动。",
                "expected_fields": ["process_name"],
                "confidence": min(0.9, 0.4 + cnt * 0.05),
                "source": "ai_heuristic",
            }
        if type_counter:
            top_type, cnt = type_counter.most_common(1)[0]
            return {
                "name": self._safe_name(f"ai_event_{top_type}"),
                "rule_type": "list",
                "condition": {
                    "field": "event_type",
                    "values": [top_type],
                    "match_mode": "exact",
                },
                "severity": "low",
                "label": f"AI 归纳：事件类型 {top_type}",
                "rationale": f"样本中事件类型 {top_type} 出现 {cnt} 次。",
                "expected_fields": ["event_type"],
                "confidence": min(0.8, 0.3 + cnt * 0.05),
                "source": "ai_heuristic",
            }
        return {
            "name": self._safe_name("ai_generic"),
            "rule_type": "exists",
            "condition": {"field": "event_type"},
            "severity": "low",
            "label": "AI 归纳：存在任意事件",
            "rationale": "样本不足，生成占位规则。",
            "expected_fields": ["event_type"],
            "confidence": 0.2,
            "source": "ai_heuristic",
        }

    @staticmethod
    def _safe_name(name: str) -> str:
        s = re.sub(r"[^a-zA-Z0-9_]", "_", str(name)).strip("_").lower()
        if not s:
            s = "ai_rule"
        return s
