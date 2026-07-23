"""前端字段投影服务（v2.1 FrontendProjection 模块）.

职责：从 CanonicalEvent / security_events 行派生「必填 / 辅助」两级展示字段，
供分析中心前端直接渲染（详见 analysis_center_optimization_design.md §10）。

- 必填 14 项：列表/卡片默认可见，应急分诊的"标题栏"。
- 辅助 9 项：详情抽屉按需加载。
- 证据详情提供双视图：范式化视图（结构化投影）+ 完整原始数据（采集端全量原始 JSON）。

本模块**不做数据加工**，仅做展示裁剪与分级；所有派生值来自 event_enrichment 等上游服务。
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

from app.database import get_connection
from app.services.event_enrichment import build_event_summary, calculate_risk_score
from app.services.canonical_event import CanonicalEvent, CanonicalEventDisplay

logger = logging.getLogger(__name__)


# ── 字段分级定义（与 v2.1 §10.2 完全一致）─────────────────────────────

REQUIRED_FIELDS: list[tuple[str, str, str]] = [
    ("id", "事件ID", "string"),
    ("case", "案件", "string"),
    ("host", "主机(资产)", "string"),
    ("event_type", "事件类型", "enum"),
    ("category", "事件分类", "enum"),
    ("attack_stage", "攻击阶段", "enum"),
    ("severity", "严重程度", "enum"),
    ("risk_score", "风险评分", "int(0-100)"),
    ("matched_rules", "命中规则", "list[json]"),
    ("timestamp", "发生时间", "datetime"),
    ("status", "状态", "enum"),
    ("attack_chain", "关联攻击链", "string/list"),
    ("ioc_hit", "情报命中", "bool"),
    ("summary", "摘要", "string"),
]

AUXILIARY_FIELDS: list[tuple[str, str, str]] = [
    ("process_subject", "进程主体", "json"),
    ("network_subject", "网络主体", "json"),
    ("persistence_target", "持久化落点", "string"),
    ("evidence_views", "证据详情", "json(双视图)"),
    ("assignee", "处置人", "string"),
    ("fusion_scene", "融合场景", "string"),
    ("source_collector", "数据来源", "string"),
    ("lifecycle_stage", "生命周期阶段", "enum"),
    ("timeline_ref", "时间线引用", "ref"),
]


# event_type → 事件分类（战术归类，映射 ATT&CK 战术）
EVENT_TYPE_TO_CATEGORY: dict[str, str] = {
    "process_start": "process",
    "process_terminate": "process",
    "network_outbound": "network",
    "network_listen": "network",
    "dns_query": "network",
    "registry_modify": "persistence",
    "registry_delete": "persistence",
    "file_create": "execution",
    "file_modify": "execution",
    "persistence_register": "persistence",
    "wmi_subscribe": "persistence",
    "scheduled_task": "persistence",
    "service_operation": "persistence",
    "user_login": "credential",
    "user_logout": "credential",
    "module_load": "defense_evasion",
    "driver_load": "defense_evasion",
    "pipe_connect": "lateral",
    "behavior_alert": "behavior",
    "ioc_match": "ioc",
    "file_event": "execution",
    "log_event": "discovery",
    "security_event": "defense_evasion",
    "browser_event": "discovery",
    "usb_event": "initial_access",
    "remote_control_event": "lateral",
    "ioc_event": "ioc",
}


# event_type / rule_name → MITRE ATT&CK 技术 ID 映射
EVENT_TYPE_TO_TCODE: dict[str, str] = {
    "process_start": "T1059", "process_terminate": "T1059",
    "network_outbound": "T1041", "network_listen": "T1043",
    "dns_query": "T1071.004",
    "registry_modify": "T1112", "registry_delete": "T1112",
    "file_create": "T1204.002", "file_modify": "T1565",
    "persistence_register": "T1547.001",
    "wmi_subscribe": "T1047",
    "scheduled_task": "T1053.005",
    "service_operation": "T1543.003",
    "user_login": "T1078", "user_logout": "T1078",
    "module_load": "T1055", "driver_load": "T1068",
    "pipe_connect": "T1550",
    "behavior_alert": "T1204",
}
RULE_NAME_TO_TCODE: dict[str, str] = {
    "orphan_process": "T1204", "child_of_office": "T1204.002",
    "child_of_browser": "T1204.002", "unsigned_process": "T1204",
    "nc_netcat_listener": "T1095", "suspicious_run_key": "T1547.001",
    "suspicious_service_path": "T1543.003", "suspicious_startup_folder": "T1547.001",
    "cmd_powershell_chain": "T1059.001", "startup_temp_path": "T1547.001",
    "suspicious_connection": "T1043", "scheduled_task": "T1053.005",
    "wmi_persistence": "T1047", "process_injection": "T1055",
    "short_lived_process": "T1204", "high_value_path": "T1204",
}


def infer_t_code(event_type: str, matched_rules: list) -> str:
    """从事件类型或命中规则推断 MITRE T-code。"""
    # 优先从命中规则的 rule_name 映射
    if matched_rules:
        for r in matched_rules:
            name = r.get("rule_name", "") if isinstance(r, dict) else ""
            if name in RULE_NAME_TO_TCODE:
                return RULE_NAME_TO_TCODE[name]
    # 其次从事件类型映射
    return EVENT_TYPE_TO_TCODE.get(event_type, "")


def infer_source(event_dict: dict) -> str:
    """推断告警来源。"""
    eid = event_dict.get("id", "")
    if eid.startswith("cm:"):
        return "行为分析"
    sc = event_dict.get("source_collector", "")
    if sc == "cm":
        return "行为分析"
    return "规则引擎"


def _parse_json(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}


def _get(evidence: dict, *keys, default=None):
    for k in keys:
        v = evidence.get(k)
        if v not in (None, "", [], {}):
            return v
    return default


def build_evidence_views(event_dict: dict, raw_json_path: Optional[str] = None) -> dict:
    """构建证据详情的双视图。

    视图A（范式化视图）：结构化、已投影的 evidence（人可快速读懂的"干净版"）。
    视图B（完整原始数据）：采集端上报的全量原始 JSON（零丢失溯源的唯一真相源）；
        若 host.raw_json_path 不可用，则回退为存储的 evidence，并标注 raw_source。

    Returns:
        {"normalized": {...}, "raw": {...}, "raw_source": str}
    """
    evidence = _parse_json(event_dict.get("evidence", {}))
    normalized = evidence if isinstance(evidence, dict) else {}

    raw = normalized
    raw_source = "stored_evidence"
    if raw_json_path and os.path.isfile(raw_json_path):
        try:
            with open(raw_json_path, "r", encoding="utf-8") as fh:
                host_raw = json.load(fh)
            # 优先取与 source_collector 对应的原始采集块，否则回退为整份原始 JSON
            collector = (event_dict.get("source_collector") or "").lower()
            block_key = _collector_to_raw_key(collector)
            if isinstance(host_raw, dict) and block_key and block_key in host_raw:
                raw = host_raw[block_key]
            else:
                raw = host_raw
            raw_source = f"host_raw_json:{os.path.basename(raw_json_path)}"
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("读取原始 JSON 失败 %s: %s", raw_json_path, exc)
            raw = normalized
            raw_source = "stored_evidence"

    return {"normalized": normalized, "raw": raw, "raw_source": raw_source}


def _collector_to_raw_key(collector: str) -> Optional[str]:
    """source_collector → 原始 JSON 顶层块名 的近似映射。"""
    mapping = {
        "process": "processes",
        "network": "network_connections",
        "dns": "dns",
        "registry": "registry_keys",
        "file": "file_hashes",
        "persistence": "persistence_items",
        "wmi": "wmi_subscriptions",
        "startup": "startup_items",
        "service": "services",
        "user": "users",
    }
    return mapping.get(collector)


def project_event(event_dict: dict, raw_json_path: Optional[str] = None) -> dict:
    """将单条事件投影为前端展示结构（必填 + 辅助 + 证据双视图）。

    Args:
        event_dict: 已 join 出 hostname / case_name 的事件字典。
        raw_json_path: 宿主机的原始采集 JSON 路径（用于视图B）。

    Returns:
        {
          "required": [{"key","label","type","value"}, ...],   # 14 项
          "auxiliary": [{"key","label","type","value"}, ...],  # 9 项
          "evidence_views": {"normalized","raw","raw_source"},
        }
    """
    evidence = _parse_json(event_dict.get("evidence", {}))
    host_label = event_dict.get("hostname") or f"主机{event_dict.get('host_id', '?')}"
    ip = event_dict.get("ip_address") or ""
    host_display = f"{host_label}" + (f" ({ip})" if ip else "")

    matched = _parse_json(event_dict.get("matched_rules", []))
    ioc = _parse_json(event_dict.get("ioc_matches", []))
    related = _parse_json(event_dict.get("related_events", []))
    attack_chain_id = event_dict.get("attack_chain_id")

    risk_score = calculate_risk_score({
        "severity": event_dict.get("severity", "info"),
        "matched_rules": matched if isinstance(matched, list) else [],
        "ioc_matches": ioc if isinstance(ioc, list) else [],
        "evidence": evidence,
    })
    summary = build_event_summary({
        **event_dict,
        "evidence": evidence,
        "hostname": event_dict.get("hostname"),
    })

    category = EVENT_TYPE_TO_CATEGORY.get(event_dict.get("event_type", ""), "unknown")
    case_display = event_dict.get("case_name") or event_dict.get("case_number") or ""

    required_values = {
        "id": event_dict.get("id"),
        "case": case_display,
        "host": host_display,
        "event_type": event_dict.get("event_type"),
        "category": category,
        "attack_stage": event_dict.get("attack_stage"),
        "severity": event_dict.get("severity"),
        "risk_score": risk_score,
        "matched_rules": matched,
        # 发生时间：事件真实发生的时间（原始主机上的时间戳）
        "timestamp": event_dict.get("timestamp"),
        "status": event_dict.get("status"),
        "attack_chain": attack_chain_id or (related if related else None),
        "ioc_hit": bool(ioc),
        "summary": summary,
    }

    process_subject = {
        "name": _get(evidence, "process_name", "image"),
        "pid": _get(evidence, "pid"),
        "path": _get(evidence, "process_path", "image_path"),
        "command_line": _get(evidence, "command_line"),
        "parent": _get(evidence, "parent_name", "parent_process_name"),
    }
    network_subject = {
        "src": _get(evidence, "local_address", "src_address"),
        "dst": _get(evidence, "remote_address", "dst_address"),
        "port": _get(evidence, "remote_port", "dst_port"),
        "protocol": _get(evidence, "protocol"),
    }
    persistence_target = _get(evidence, "key_path", "service_path", "startup_path", "location")

    auxiliary_values = {
        "process_subject": process_subject,
        "network_subject": network_subject,
        "persistence_target": persistence_target,
        "evidence_views": build_evidence_views(event_dict, raw_json_path),
        "assignee": event_dict.get("assignee"),
        "fusion_scene": event_dict.get("fusion_scene"),
        "source_collector": event_dict.get("source_collector"),
        "lifecycle_stage": event_dict.get("lifecycle_stage") or event_dict.get("status"),
        "timeline_ref": event_dict.get("timeline_ref"),
    }

    required = [
        {"key": k, "label": lbl, "type": t, "value": required_values.get(k)}
        for (k, lbl, t) in REQUIRED_FIELDS
    ]
    auxiliary = [
        {"key": k, "label": lbl, "type": t, "value": auxiliary_values.get(k)}
        for (k, lbl, t) in AUXILIARY_FIELDS
    ]

    return {
        "required": required,
        "auxiliary": auxiliary,
        "evidence_views": auxiliary_values["evidence_views"],
    }


def get_event_display(event_id: str) -> Optional[dict]:
    """加载单条事件的完整展示投影（供 GET /api/events/{id}/display）。

    Returns:
        {"event_id", "projection": {...}, "host_raw_json_path": str|None}
        事件不存在返回 None。
    """
    with get_connection() as conn:
        # 先用 _lookup_event 解析各种 event_id 格式，获取真实 id
        from app.api.events import _lookup_event
        resolved = _lookup_event(conn, event_id, join_hosts=False)
        if not resolved:
            return None
        real_id = resolved["id"]

        # 用解析后的真实 id 做完整 JOIN 查询（含 raw_json_path）
        row = conn.execute(
            """
            SELECT se.*, h.hostname, h.ip_address, h.raw_json_path,
                   c.name as case_name, c.case_number
            FROM security_events se
            LEFT JOIN hosts h ON h.id = se.host_id
            LEFT JOIN cases c ON c.id = h.case_id
            WHERE se.id = ?
            """,
            (real_id,),
        ).fetchone()
        if not row:
            return None

        event_dict = dict(row)
        # 融合场景：从 incident_correlations 反查（host 命中即视为该事件所属战役）
        fusion = None
        try:
            host_id = event_dict.get("host_id")
            if host_id:
                corr = conn.execute(
                    "SELECT title FROM incident_correlations WHERE host_ids LIKE ? ORDER BY id DESC LIMIT 1",
                    (f'%"{host_id}"%',),
                ).fetchone()
                if corr:
                    fusion = corr["title"]
        except Exception as exc:  # 表可能不存在
            logger.debug("融合场景查询跳过: %s", exc)
        event_dict["fusion_scene"] = fusion

    raw_path = event_dict.get("raw_json_path")
    projection = project_event(event_dict, raw_path)
    return {
        "event_id": event_id,
        "event": event_dict,
        "projection": projection,
        "host_raw_json_path": raw_path,
    }


# ===================================================================
#  FrontendProjection 类（v2 §3 类化接口）
# ===================================================================


class FrontendProjection:
    """前端字段投影 — 从 CanonicalEvent 派生必填/辅助分级视图。

    与 §3 接口定义一致，内部复用现有 project_event 等函数。
    """

    @staticmethod
    def from_event_dict(event_dict: dict, raw_json_path: Optional[str] = None) -> CanonicalEventDisplay:
        """从事件字典投影（兼容旧调用方）。"""
        proj = project_event(event_dict, raw_json_path)
        return CanonicalEventDisplay(
            required=proj["required"],
            auxiliary=proj["auxiliary"],
            evidence_views=proj["evidence_views"],
        )

    @staticmethod
    def project(ce: CanonicalEvent) -> CanonicalEventDisplay:
        """从 CanonicalEvent 派生展示视图（§3 project() 签名）。"""
        event_dict = {
            "id": ce.event_uid,
            "event_type": ce.event_type,
            "severity": ce.severity,
            "status": ce.status,
            "host_id": ce.host_id,
            "hostname": ce.hostname,
            "ip_address": ce.ip_address,
            "timestamp": ce.timestamp,
            "attack_stage": ce.attack_stage,
            "attack_chain_id": None,
            "matched_rules": "[]",
            "ioc_matches": "[]",
            "evidence": ce.evidence,
            "assignee": ce.assignee,
            "source_collector": ce.source,
            "case_name": None,
            "case_number": None,
            "fusion_scene": None,
            "related_events": "[]",
            "lifecycle_stage": ce.lifecycle_state,
            "timeline_ref": None,
        }
        return FrontendProjection.from_event_dict(event_dict, ce.raw_json_path)
