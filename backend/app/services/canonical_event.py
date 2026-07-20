"""统一规范事件模型（v2 CanonicalEventModel）.

定义 CanonicalEvent dataclass 与 CanonicalEventDisplay 展示视图。
两端（AC security_events / CM 分析结果表）所有事件先映射为 CanonicalEvent，
再决定落库/展示，确保字段、状态、分类、生命周期四统一。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional


# ── 统一状态枚举（§5.4 状态机）────────────────────────────────────
EVENT_STATUS_CYCLE: list[str] = [
    "pending", "triaging", "investigating", "resolved", "rejected",
]
VALID_EVENT_STATUS: set[str] = set(EVENT_STATUS_CYCLE)

VALID_SEVERITIES: set[str] = {"critical", "high", "medium", "low", "info"}


# ── 统一分类枚举（§5.4 分类对齐）───────────────────────────────────
CATEGORY_ENUM: set[str] = {
    "process", "network", "persistence", "startup", "behavior",
    "ioc", "credential", "discovery", "execution", "defense_evasion",
    "lateral", "exfiltration", "c2", "impact", "unknown",
}


@dataclass
class CanonicalEventDisplay:
    """前端展示视图 —— 从 CanonicalEvent 派生，分级展示。

    直接对应 §10 的必填 14 项 + 辅助 9 项 + 证据双视图。
    """
    required: list[dict] = field(default_factory=list)       # [{"key","label","type","value"}, ...]
    auxiliary: list[dict] = field(default_factory=list)      # [同上]
    evidence_views: dict = field(default_factory=dict)       # {normalized, raw, raw_source}


@dataclass
class CanonicalEvent:
    """统一规范事件（§3/§5）—— 所有来源最终映射为此模型。

    字段设计覆盖 AC（security_events）和 CM（abnormal_processes 等表）
    的两端共性，同时保留差异字段在 evidence 中传递。
    """
    # ── 核心标识 ──
    event_uid: str                                          # 全局唯一: "{source}:{source_event_id}"
    source: str                                             # "ac" | "cm"
    source_event_id: str                                    # 原始表主键
    host_id: int
    case_id: Optional[int] = None
    event_type: str = "unknown"

    # ── 安全分类 ──
    category: str = "unknown"                               # 统一枚举，含 behavior
    attack_stage: Optional[str] = None
    severity: str = "medium"
    risk_score: int = 0

    # ── 处置字段 ──
    status: str = "pending"
    assignee: Optional[str] = None

    # ── 时间与证据 ──
    timestamp: str = ""
    evidence: dict = field(default_factory=dict)            # 结构化证据

    # ── 规则匹配（CM 事件预填充，AC 事件由 rule_matcher 填充）──
    matched_rules_str: str = "[]"                           # JSON 字符串，供 security_events 列直接写入

    # ── 管道元信息 ──
    lifecycle_state: str = "collected"
    version: int = 1                                        # 乐观锁
    updated_at: str = ""
    hostname: Optional[str] = None
    ip_address: Optional[str] = None
    raw_json_path: Optional[str] = None

    # ── 展示视图（投影层填充）──
    display: Optional[CanonicalEventDisplay] = None

    def __post_init__(self):
        """初始化后自动规范化字段。"""
        # 状态校验
        if self.status not in VALID_EVENT_STATUS:
            self.status = "pending"
        # 严重级别校验
        if self.severity not in VALID_SEVERITIES:
            self.severity = "medium"
        # 分类校验
        if self.category not in CATEGORY_ENUM:
            self.category = "unknown"
        if not self.event_uid:
            self.event_uid = f"{self.source}:{self.source_event_id}"
        # lifecycle_state 默认值
        if not self.lifecycle_state:
            self.lifecycle_state = "collected"

    def to_dict(self) -> dict:
        """转为普通字典（不含 display）。"""
        return {
            "event_uid": self.event_uid,
            "source": self.source,
            "source_event_id": self.source_event_id,
            "host_id": self.host_id,
            "case_id": self.case_id,
            "event_type": self.event_type,
            "category": self.category,
            "attack_stage": self.attack_stage,
            "severity": self.severity,
            "risk_score": self.risk_score,
            "status": self.status,
            "assignee": self.assignee,
            "timestamp": self.timestamp,
            "evidence": self.evidence,
            "lifecycle_state": self.lifecycle_state,
            "version": self.version,
            "updated_at": self.updated_at,
            "hostname": self.hostname,
            "ip_address": self.ip_address,
            "raw_json_path": self.raw_json_path,
        }

    def to_engine_item(self) -> dict:
        """将嵌套 evidence 扁平化为 RuleEngine 期望的字段（供 MatcherRegistry 消费）.

        实时链路（security_events）的 evidence 是嵌套结构，字段名如 process_name /
        process_path / parent_process_name；而分析链路（abnormal_processes）使用扁平字段
        name / path / parent_name。本方法产出一份**同时保留原始 evidence 字段**且补齐
        引擎约定别名（name / path / parent_name / remote_address / remote_port）的扁平 dict，
        使 RuleEngine 的 7 类 matcher（读扁平字段）在实时与分析两条链路下语义一致。

        Returns:
            扁平化数据项字典。
        """
        evidence = self.evidence if isinstance(self.evidence, dict) else {}
        item: dict = dict(evidence)  # 保留所有原始嵌套-扁平字段

        # ── 引擎约定别名（实时 evidence 字段 → 分析扁平字段）──
        if not item.get("name"):
            item["name"] = evidence.get("process_name") or evidence.get("name")
        if not item.get("path"):
            item["path"] = evidence.get("process_path") or evidence.get("path")
        if not item.get("parent_name"):
            item["parent_name"] = (
                evidence.get("parent_name") or evidence.get("parent_process_name")
            )
        if "host_id" not in item:
            item["host_id"] = self.host_id
        if "event_type" not in item:
            item["event_type"] = self.event_type
        if "category" not in item:
            item["category"] = self.category
        if "remote_address" not in item:
            item["remote_address"] = evidence.get("remote_address") or evidence.get("dst_ip")
        if "remote_port" not in item:
            item["remote_port"] = evidence.get("remote_port") or evidence.get("dst_port")
        return item


# ===================================================================
#  辅助：JSON 兼容序列化
# ===================================================================

def security_event_row_to_canonical(row: dict) -> "CanonicalEvent":
    """将 security_events 表行映射为 CanonicalEvent（统一输入契约）.

    作为实时与分析链路的唯一输入契约：security_events 行 → CanonicalEvent →
    to_engine_item() 扁平化 → RuleEngine.evaluate。

    Args:
        row: security_events 表行字典（含 evidence JSON 字段、host_id、event_type 等）.

    Returns:
        CanonicalEvent 实例。
    """
    evidence = row.get("evidence")
    if isinstance(evidence, str):
        try:
            evidence = json.loads(evidence)
        except (json.JSONDecodeError, TypeError):
            evidence = {}
    if not isinstance(evidence, dict):
        evidence = {}

    return CanonicalEvent(
        event_uid=str(row.get("id") or f"{row.get('source_collector', 'ac')}:{row.get('event_key')}"),
        source=row.get("source_collector") or "ac",
        source_event_id=str(row.get("event_key") or row.get("id") or ""),
        host_id=int(row.get("host_id") or 0),
        event_type=row.get("event_type") or "unknown",
        category=row.get("category") or "unknown",
        severity=row.get("severity") or "medium",
        timestamp=row.get("timestamp") or "",
        evidence=evidence,
        hostname=row.get("hostname"),
        ip_address=row.get("ip_address"),
    )


def canonical_event_to_security_event_row(ce: CanonicalEvent) -> dict:
    """将 CanonicalEvent 转为 security_events 表行.
    
    Args:
        ce: 规范事件.
    
    Returns:
        可直接插入 security_events 的字典.
    """
    return {
        "id": ce.event_uid,
        "event_type": ce.event_type,
        "severity": ce.severity,
        "status": ce.status,
        "host_id": ce.host_id,
        "timestamp": ce.timestamp,
        "attack_stage": ce.attack_stage,
        "attack_chain_id": None,
        "event_key": str(ce.source_event_id),
        "matched_rules": ce.matched_rules_str,
        "ioc_matches": "[]",
        "evidence": json.dumps(ce.evidence, ensure_ascii=False),
        "assignee": ce.assignee,
        "related_events": "[]",
        "source_collector": ce.source,
        "created_at": ce.updated_at,
        "updated_at": ce.updated_at,
    }
