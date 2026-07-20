"""检测策略门控（DetectionPolicy）— 实时与分析共用同一实例，保证门控一致.

设计文档 §8.2：单一 DetectionPolicy 同时作用于实时与分析链路，消除
"分析能看到攻击链、实时看不到"的漏报。enable_attack_chain 控制是否跑攻击链；
mode 仅影响候选范围（实时按 category 预筛），不影响门控逻辑。
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DetectionPolicy:
    """统一检测策略门控.

    Attributes:
        enable_attack_chain: 是否启用攻击链主机级关联（实时+分析共用）。
        mode: 运行模式，"realtime" | "analysis"。仅影响候选范围，不影响门控。
        active_severities: 参与告警的严重级别集合。
        shadow_mode: 影子模式开关（仅计数、不告警）。
    """

    enable_attack_chain: bool = True
    mode: str = "analysis"  # "realtime" | "analysis"
    active_severities: set = field(
        default_factory=lambda: {"low", "medium", "high", "critical"}
    )
    shadow_mode: bool = False

    def is_severity_active(self, severity: str) -> bool:
        """判断某严重级别是否参与告警."""
        return severity in self.active_severities

    def for_mode(self, mode: str) -> "DetectionPolicy":
        """返回同门控、不同 mode 的副本（候选范围切换用）."""
        return DetectionPolicy(
            enable_attack_chain=self.enable_attack_chain,
            mode=mode,
            active_severities=set(self.active_severities),
            shadow_mode=self.shadow_mode,
        )
