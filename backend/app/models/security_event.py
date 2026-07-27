"""SecurityEvent 数据模型与常量定义."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime


# ── 事件类型枚举 ──

EVENT_TYPES = [
    "process_start",
    "process_terminate",
    "network_outbound",
    "network_listen",
    "registry_modify",
    "registry_delete",
    "file_create",
    "file_modify",
    "persistence_register",
    "wmi_subscribe",
    "behavior_alert",
    "ioc_match",
    "user_login",
    "user_logout",
    "dns_query",
    "module_load",
    "scheduled_task",
    "service_operation",
    "pipe_connect",
    "driver_load",
    "log_event",
]

EVENT_TYPE_LABELS = {
    "process_start": "进程启动",
    "process_terminate": "进程退出",
    "network_outbound": "出站连接",
    "network_listen": "端口监听",
    "registry_modify": "注册表写入",
    "registry_delete": "注册表删除",
    "file_create": "文件创建",
    "file_modify": "文件修改",
    "persistence_register": "持久化注册",
    "wmi_subscribe": "WMI订阅",
    "behavior_alert": "行为告警",
    "ioc_match": "IOC命中",
    "user_login": "用户登录",
    "user_logout": "用户登出",
    "dns_query": "DNS查询",
    "module_load": "模块加载",
    "scheduled_task": "计划任务",
    "service_operation": "服务操作",
    "pipe_connect": "管道连接",
    "driver_load": "驱动加载",
    "log_event": "安全日志",
}

# ── 严重等级 ──

SEVERITY_LEVELS = ["critical", "high", "medium", "low", "info"]

SEVERITY_COLORS = {
    "critical": "#DC2626",
    "high": "#EF4444",
    "medium": "#EAB308",
    "low": "#3B82F6",
    "info": "#9CA3AF",
}

# ── 处置状态 ──

STATUSES = ["pending", "triaging", "investigating", "resolved", "rejected"]

STATUS_COLORS = {
    "pending": "#9CA3AF",
    "triaging": "#3B82F6",
    "investigating": "#F97316",
    "resolved": "#22C55E",
    "rejected": "#EF4444",
}

STATUS_FLOW: dict[str, set[str]] = {
    "pending": {"triaging", "rejected"},
    "triaging": {"investigating", "rejected", "pending"},
    "investigating": {"resolved", "rejected"},
    "resolved": {"investigating"},
    "rejected": set(),
}

# ── ATT&CK 阶段 ──

ATTACK_STAGES = [
    "initial_access",
    "execution",
    "persistence",
    "privilege_escalation",
    "defense_evasion",
    "credential_access",
    "discovery",
    "lateral_movement",
    "collection",
    "command_and_control",
    "exfiltration",
    "impact",
    "unknown",
]

ATTACK_STAGE_COLORS = {
    "initial_access": "#FFE0E0",
    "execution": "#FFF3E0",
    "persistence": "#FFFDE7",
    "privilege_escalation": "#F3E5F5",
    "defense_evasion": "#E8EAF6",
    "credential_access": "#E0F2F1",
    "discovery": "#E8F5E9",
    "lateral_movement": "#FFF3E0",
    "collection": "#FCE4EC",
    "command_and_control": "#EFEBE9",
    "exfiltration": "#FFEBEE",
    "impact": "#FFCDD2",
    "unknown": "#F5F5F5",
}

ATTACK_STAGE_LABELS = {
    "initial_access": "初始访问",
    "execution": "执行",
    "persistence": "持久化",
    "privilege_escalation": "提权",
    "defense_evasion": "防御规避",
    "credential_access": "凭据访问",
    "discovery": "发现",
    "lateral_movement": "横向移动",
    "collection": "收集",
    "command_and_control": "C2",
    "exfiltration": "数据外泄",
    "impact": "影响",
    "unknown": "未知",
}

# 基于 event_type 的默认 ATT&CK 阶段映射
ATTACK_STAGE_MAP: dict[str, str | None] = {
    "process_start": "execution",
    "network_outbound": "command_and_control",
    "dns_query": "command_and_control",
    "network_listen": "command_and_control",
    "persistence_register": "persistence",
    "scheduled_task": "persistence",
    "service_operation": "persistence",
    "registry_modify": "privilege_escalation",
    "registry_delete": "defense_evasion",
    "process_terminate": "defense_evasion",
    "module_load": "defense_evasion",
    "driver_load": "defense_evasion",
    "file_create": "collection",
    "file_modify": "impact",
    "user_login": "initial_access",
    "wmi_subscribe": "execution",
    "pipe_connect": "lateral_movement",
    "behavior_alert": "execution",
    "ioc_match": "initial_access",
    "user_logout": None,
    "log_event": None,    # ← 由 Event ID 决定阶段
}


@dataclass
class SecurityEvent:
    """统一安全事件模型."""

    id: str = ""
    timestamp: str = ""
    host_id: int = 0
    event_type: str = ""
    severity: str = "info"
    source_collector: str = ""
    event_key: str = ""
    attack_chain_id: str | None = None
    attack_stage: str | None = None
    ioc_matches: list[str] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)
    status: str = "pending"
    assignee: str | None = None
    related_events: list[str] = field(default_factory=list)
    matched_rules: list = field(default_factory=list)  # 规则匹配结果
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        """转换为可序列化的字典."""
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "host_id": self.host_id,
            "event_type": self.event_type,
            "severity": self.severity,
            "source_collector": self.source_collector,
            "event_key": self.event_key,
            "attack_chain_id": self.attack_chain_id,
            "attack_stage": self.attack_stage,
            "ioc_matches": self.ioc_matches,
            "evidence": self.evidence,
            "status": self.status,
            "assignee": self.assignee,
            "related_events": self.related_events,
            "matched_rules": self.matched_rules,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_row(cls, row: dict) -> "SecurityEvent":
        """从 sqlite3.Row 构建实例."""
        return cls(
            id=row["id"],
            timestamp=row["timestamp"],
            host_id=row["host_id"],
            event_type=row["event_type"],
            severity=row["severity"],
            source_collector=row.get("source_collector", ""),
            event_key=row.get("event_key", ""),
            attack_chain_id=row.get("attack_chain_id"),
            attack_stage=row.get("attack_stage"),
            ioc_matches=json.loads(row.get("ioc_matches", "[]")),
            evidence=json.loads(row.get("evidence", "{}")),
            status=row["status"],
            assignee=row.get("assignee"),
            related_events=json.loads(row.get("related_events", "[]")),
            matched_rules=json.loads(row.get("matched_rules", "[]")),
            created_at=row.get("created_at", ""),
            updated_at=row.get("updated_at", ""),
        )

    def validate_status_transition(self, new_status: str) -> tuple[bool, str]:
        """验证状态流转是否合法."""
        allowed = STATUS_FLOW.get(self.status, set())
        if new_status in allowed:
            return True, ""
        return False, f"不允许从 '{self.status}' 流转到 '{new_status}'"


def infer_attack_stage(event_type: str, evidence: dict | None = None) -> str | None:
    """根据 event_type 和 evidence 推断 ATT&CK 阶段."""
    stage = ATTACK_STAGE_MAP.get(event_type)
    if stage:
        return stage
    # fallback: evidence 中查找 attack_stage 标记
    if evidence and isinstance(evidence, dict):
        if "attack_stage" in evidence:
            return evidence["attack_stage"]
    return "unknown"


def make_event_id(host_id: int, event_type: str, event_key: str) -> str:
    """生成事件唯一 ID: sha256(host_id + event_type + event_key)."""
    import hashlib
    raw = f"{host_id}:{event_type}:{event_key}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]
