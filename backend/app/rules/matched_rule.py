"""MatchedRule — 统一引擎产出结构（设计 §4.4）.

实时与分析两链路共用 RuleEngine.evaluate，均产出 MatchedRule 字典。
gated_by 标记该命中被何种门控排除（null=真实命中需告警；
suppression/whitelist/false_positive=被闭环门控排除、仅记录不告警）。
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class MatchedRule:
    """统一引擎命中产物.

    Attributes:
        item: 触发命中的扁平化数据项（attack_chain 时为虚拟 host 事件）。
        rule: 命中的完整规则字典（供下游消费）。
        rule_id: 规则 ID.
        rule_name: 规则名（门控/抑制/误报均以 rule_name 为键）.
        rule_type: 规则类型（7 类之一）.
        category: 规则类别.
        severity: 命中严重级别（攻击链强制 critical）.
        confidence: 置信度（按类型/行为模式映射）.
        reason: 命中原因说明.
        matched_fields: 命中的关键字段快照.
        matched_dimension: 行为命中的维度归属（非行为为 None）.
        attack_chain: 攻击链关联结果明细（非攻击链为 None）.
        gated_by: 门控标记（null | "suppression" | "whitelist" | "false_positive"）.
        auto_playbook: 自动 Playbook 触发配置（P1-4 填充，默认 None）.
    """

    item: dict
    rule: dict
    rule_id: Optional[int]
    rule_name: str
    rule_type: str
    category: Optional[str]
    severity: str
    confidence: float
    reason: str
    matched_fields: dict
    matched_dimension: Optional[str]
    attack_chain: Optional[dict]
    gated_by: Optional[str]
    auto_playbook: Optional[dict] = None

    def to_dict(self) -> dict:
        """转为普通字典（供 match_event / API 返回 / 落库消费）."""
        return {
            "item": self.item,
            "rule": self.rule,
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "rule_type": self.rule_type,
            "category": self.category,
            "severity": self.severity,
            "confidence": self.confidence,
            "reason": self.reason,
            "matched_fields": self.matched_fields,
            "matched_dimension": self.matched_dimension,
            "attack_chain": self.attack_chain,
            "gated_by": self.gated_by,
            "auto_playbook": self.auto_playbook,
        }
