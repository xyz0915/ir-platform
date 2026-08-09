"""Agent 抽象基类 — 所有智能体的公共契约（§8.1）."""

import abc
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from app.services.agent_llm import AgentLLM

logger = logging.getLogger(__name__)


@dataclass
class AgentResult:
    """单个 Agent 的执行结果（统一结构，便于编排器汇聚）。

    Attributes:
        stage: 所属阶段（triage|investigation|response|report）。
        output: 文本化输出（分析报告 / 处置建议 / 结论）。
        confidence: 置信度 0~1（默认 0.0）。
        evidence: 证据列表，元素为 ``{"type": str, "ref": str}``，指向真实数据域。
        hitl: 是否触发人在回路（requires_hitl 且未达免审批阈值时置 True）。
        execution_duration_ms: 本阶段执行耗时（毫秒）。
        llm_calls_count: LLM 调用次数。
        usage: Token 用量。
        error: 异常信息。
        data_sources: 数据源引用列表。
        degraded_reason: 降级原因（P2-13，供前端结构化展示；正常路径为 None）。
    """

    stage: str = "triage"
    output: str = ""
    confidence: float = 0.0
    evidence: list[dict] = field(default_factory=list)
    hitl: bool = False
    # 新增字段
    execution_duration_ms: float = 0.0
    llm_calls_count: int = 0
    usage: dict = field(default_factory=dict)
    error: Optional[str] = None
    data_sources: list = field(default_factory=list)
    degraded_reason: Optional[str] = None  # P2-13：带默认值置于末尾，不破坏位置参数构造

    def to_dict(self) -> dict:
        """序列化为 dict（写入 agent_run_steps.output_json / result_json）。"""
        return {
            "stage": self.stage,
            "output": self.output,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "hitl": self.hitl,
            "execution_duration_ms": self.execution_duration_ms,
            "llm_calls_count": self.llm_calls_count,
            "usage": self.usage,
            "error": self.error,
            "data_sources": self.data_sources,
            "degraded_reason": self.degraded_reason,  # P2-13
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AgentResult":
        """从 dict 还原 AgentResult（使用 .get() 兼容旧数据）。"""
        return cls(
            stage=data.get("stage", "triage"),
            output=data.get("output", ""),
            confidence=float(data.get("confidence", 0.0)),
            evidence=data.get("evidence", []) or [],
            hitl=bool(data.get("hitl", False)),
            execution_duration_ms=float(data.get("execution_duration_ms", 0.0)),
            llm_calls_count=int(data.get("llm_calls_count", 0)),
            usage=data.get("usage", {}) or {},
            error=data.get("error"),
            data_sources=data.get("data_sources", []) or [],
            degraded_reason=data.get("degraded_reason"),  # P2-13：.get() 兼容历史 output_json
        )


class BaseAgent(abc.ABC):
    """智能体抽象基类。

    子类必须实现 ``run``；可重写 ``_build_prompt`` / ``_parse`` 钩子。
    共享：名称/角色/是否需要 HITL/置信度阈值，以及结果落库辅助。
    """

    # ── 子类需覆盖的类属性 ──
    name: str = "base_agent"
    role: str = "通用智能体"
    requires_hitl: bool = False
    confidence_threshold: float = 0.7

    def __init__(self) -> None:
        self._llm = AgentLLM()

    @abc.abstractmethod
    async def run(self, ctx: dict, task: dict) -> "AgentResult":
        """执行智能体逻辑。

        Args:
            ctx: 运行上下文（含 host_id / event 数据 / 历史步骤等）。
            task: 本次任务参数（来自编排器下发）。

        Returns:
            AgentResult 实例。
        """
        raise NotImplementedError

    def _build_prompt(self, ctx: dict, task: dict) -> str:
        """构建发送给 LLM 的提示词（默认空，子类按需重写）。"""
        return ""

    def _parse(self, resp: str, ctx: dict) -> "AgentResult":
        """解析 LLM 响应为 AgentResult（默认直接包装，子类按需重写）。"""
        return AgentResult(
            stage=self._stage(),
            output=resp or "",
            confidence=self.confidence_threshold,
        )

    def _stage(self) -> str:
        """根据 name 推导默认 stage（triage/investigation/response/report）。"""
        n = (self.name or "").lower()
        if "triage" in n:
            return "triage"
        if "invest" in n:
            return "investigation"
        if "respond" in n or "responder" in n:
            return "response"
        if "report" in n:
            return "report"
        return "triage"

    @property
    def description(self) -> str:
        """可读描述（调试/日志用）。"""
        return f"{self.name}::{self.role}"
