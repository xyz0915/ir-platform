"""事件归一化服务：将 20+ 类 Agent 原始数据归一化为 SecurityEvent 模型.

管道架构:
  Schema Validator → Type Router → Mapper Chain → Attack Stage Classifier → Dedup Filter → Batch Inserter
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

from app.database import get_connection
from app.models.security_event import (
    EVENT_TYPES,
    SecurityEvent,
    infer_attack_stage,
    make_event_id,
)

logger = logging.getLogger(__name__)


def _compute_raw_extra(raw: dict, extracted_keys: set) -> dict:
    """计算原始数据中未被 Mapper 显式提取的字段，注入到 evidence._raw_extra。

    过滤规则：
    1. 仅保留标量值（str/int/float/bool），排除嵌套 dict/list
    2. 排除 '_' 开头的内部字段（_fallback_ts, _persist_path 等）
    3. 排除已经被显式提取的 key（extracted_keys）
    4. 排除 _raw_extra 自身（防止无限递归）
    5. 每个字段值截断到 500 字符，总大小不超过 16KB
    """
    SCALAR_TYPES = (str, int, float, bool)
    MAX_FIELD_LENGTH = 500
    MAX_TOTAL_BYTES = 16 * 1024
    result = {}
    total_size = 0
    for k, v in raw.items():
        if k in extracted_keys:
            continue
        if k.startswith("_"):
            continue
        if k == "_raw_extra":
            continue
        if not isinstance(v, SCALAR_TYPES):
            continue
        if isinstance(v, str) and len(v) > MAX_FIELD_LENGTH:
            v = v[:MAX_FIELD_LENGTH]
        val_bytes = len(str(v).encode("utf-8"))
        if total_size + val_bytes > MAX_TOTAL_BYTES:
            continue
        result[k] = v
        total_size += val_bytes
    return result

# ── 批量写入配置 ──
BATCH_SIZE = 500
FLUSH_INTERVAL = 1.0  # 秒


# ===================================================================
#  映射器基类与具体映射器
# ===================================================================


class BaseMapper:
    """映射器基类."""

    event_types: list[str] = []

    def map(self, raw: dict) -> dict | None:
        """将原始数据映射为 SecurityEvent 字段字典。

        Args:
            raw: Agent 上报的原始 JSON 数据.

        Returns:
            包含 SecurityEvent 字段的字典，或 None（映射失败时跳过的降级结果）。
        """
        raise NotImplementedError


class ProcessMapper(BaseMapper):
    """进程事件映射器: process_start / process_terminate."""

    event_types = ["process_start", "process_terminate"]
    _EXTRACTED_KEYS = {
        "event_type", "pid", "ppid", "process_name", "process_path",
        "command_line", "parent_name", "session", "timestamp",
        "source_collector", "severity", "host_id",
    }

    def map(self, raw: dict) -> dict | None:
        return {
            "event_type": raw.get("event_type", "process_start"),
            "event_key": str(raw.get("pid", raw.get("process_name", "unknown"))),
            "timestamp": raw.get("timestamp", raw.get("start_time", raw.get("_fallback_ts", datetime.now(timezone.utc).isoformat()))),
            "source_collector": raw.get("source_collector", "osquery"),
            "evidence": {
                "name": raw.get("process_name"),       # ← 规则匹配需要 name 字段
                "pid": raw.get("pid"),
                "ppid": raw.get("ppid"),
                "process_name": raw.get("process_name"),
                "process_path": raw.get("process_path"),
                "command_line": raw.get("command_line"),
                "parent_name": raw.get("parent_name"),
                "session": raw.get("session"),
                "_raw_extra": _compute_raw_extra(raw, self._EXTRACTED_KEYS),
            },
            "severity": raw.get("severity", "medium"),
            "host_id": raw.get("host_id", 0),
        }


class NetworkMapper(BaseMapper):
    """网络事件映射器: network_outbound / network_listen / dns_query."""

    event_types = ["network_outbound", "network_listen", "dns_query"]
    _EXTRACTED_KEYS = {
        "event_type", "protocol", "local_address", "local_addr", "local_port",
        "remote_address", "remote_addr", "remote_port", "state", "process_name",
        "pid", "query", "query_type", "timestamp", "source_collector",
        "severity", "host_id",
    }

    def map(self, raw: dict) -> dict | None:
        return {
            "event_type": raw.get("event_type", "network_outbound"),
            "event_key": f"{raw.get('remote_address', '')}:{raw.get('remote_port', 0)}",
            "timestamp": raw.get("timestamp", raw.get("_fallback_ts", datetime.now(timezone.utc).isoformat())),
            "source_collector": raw.get("source_collector", "osquery"),
            "evidence": {
                "protocol": raw.get("protocol"),
                "local_address": raw.get("local_address", raw.get("local_addr")),
                "local_port": raw.get("local_port"),
                "remote_address": raw.get("remote_address", raw.get("remote_addr")),
                "remote_port": raw.get("remote_port"),
                "state": raw.get("state"),
                "process_name": raw.get("process_name"),
                "pid": raw.get("pid"),
                "query": raw.get("query"),  # DNS
                "query_type": raw.get("query_type"),
                "_raw_extra": _compute_raw_extra(raw, self._EXTRACTED_KEYS),
            },
            "severity": raw.get("severity", "medium"),
            "host_id": raw.get("host_id", 0),
        }


class RegistryMapper(BaseMapper):
    """注册表事件映射器: registry_modify / registry_delete."""

    event_types = ["registry_modify", "registry_delete"]
    _EXTRACTED_KEYS = {
        "event_type", "key_path", "value_name", "value_type", "value_data",
        "process_name", "timestamp", "source_collector", "severity", "host_id",
    }

    def map(self, raw: dict) -> dict | None:
        return {
            "event_type": raw.get("event_type", "registry_modify"),
            "event_key": raw.get("key_path", ""),
            "timestamp": raw.get("timestamp", raw.get("_fallback_ts", datetime.now(timezone.utc).isoformat())),
            "source_collector": raw.get("source_collector", "osquery"),
            "evidence": {
                "key_path": raw.get("key_path"),
                "value_name": raw.get("value_name"),
                "value_type": raw.get("value_type"),
                "value_data": raw.get("value_data"),
                "command": raw.get("value_data"),      # ← 规则匹配需要 command
                "process_name": raw.get("process_name"),
                "_raw_extra": _compute_raw_extra(raw, self._EXTRACTED_KEYS),
            },
            "severity": raw.get("severity", "medium"),
            "host_id": raw.get("host_id", 0),
        }


class FileMapper(BaseMapper):
    """文件事件映射器: file_create / file_modify."""

    event_types = ["file_create", "file_modify"]
    _EXTRACTED_KEYS = {
        "event_type", "file_name", "file_path", "file_size", "sha256",
        "is_signed", "signer", "process_name", "timestamp", "source_collector",
        "severity", "host_id",
    }

    def map(self, raw: dict) -> dict | None:
        return {
            "event_type": raw.get("event_type", "file_create"),
            "event_key": raw.get("file_path", raw.get("file_name", "")),
            "timestamp": raw.get("timestamp", raw.get("_fallback_ts", datetime.now(timezone.utc).isoformat())),
            "source_collector": raw.get("source_collector", "osquery"),
            "evidence": {
                "name": raw.get("file_name"),           # ← 规则匹配需要 name
                "file_path": raw.get("file_path"),
                "file_name": raw.get("file_name"),
                "file_size": raw.get("file_size"),
                "sha256": raw.get("sha256"),
                "is_signed": raw.get("is_signed"),
                "signer": raw.get("signer"),
                "process_name": raw.get("process_name"),
                "_raw_extra": _compute_raw_extra(raw, self._EXTRACTED_KEYS),
            },
            "severity": raw.get("severity", "medium"),
            "host_id": raw.get("host_id", 0),
        }


class PersistenceMapper(BaseMapper):
    """持久化映射器: persistence_register / scheduled_task / service_operation."""

    event_types = ["persistence_register", "scheduled_task", "service_operation"]
    _EXTRACTED_KEYS = {
        "event_type", "name", "command", "path", "binary_path", "_persist_path",
        "display_name", "start_type", "status", "user", "account", "description",
        "timestamp", "source_collector", "severity", "host_id",
    }

    def map(self, raw: dict) -> dict | None:
        return {
            "event_type": raw.get("event_type", "persistence_register"),
            "event_key": raw.get("name", raw.get("command", "")),
            "timestamp": raw.get("timestamp", raw.get("_fallback_ts", datetime.now(timezone.utc).isoformat())),
            "source_collector": raw.get("source_collector", "osquery"),
            "evidence": {
                "name": raw.get("name"),
                "path": (raw.get("path")
                         or raw.get("binary_path")
                         or raw.get("_persist_path")),  # import_service 从 persistence.services.command 注入
                "display_name": raw.get("display_name"),       # 服务显示名
                "start_type": raw.get("start_type"),           # 启动类型
                "status": raw.get("status"),                   # 运行状态
                "user": raw.get("user") or raw.get("account"), # 新版/旧版兼容
                "description": raw.get("description"),         # 服务描述
                "_raw_extra": _compute_raw_extra(raw, self._EXTRACTED_KEYS),
            },
            "severity": raw.get("severity", "high"),
            "host_id": raw.get("host_id", 0),
        }


class WmiMapper(BaseMapper):
    """WMI 订阅映射器: wmi_subscribe."""

    event_types = ["wmi_subscribe"]
    _EXTRACTED_KEYS = {
        "event_type", "name", "event_filter", "event_consumer", "binding_type",
        "timestamp", "source_collector", "severity", "host_id",
    }

    def map(self, raw: dict) -> dict | None:
        return {
            "event_type": "wmi_subscribe",
            "event_key": raw.get("name", raw.get("event_filter", "")),
            "timestamp": raw.get("timestamp", raw.get("_fallback_ts", datetime.now(timezone.utc).isoformat())),
            "source_collector": raw.get("source_collector", "osquery"),
            "evidence": {
                "name": raw.get("name"),
                "event_filter": raw.get("event_filter"),
                "event_consumer": raw.get("event_consumer"),
                "binding_type": raw.get("binding_type"),
                "_raw_extra": _compute_raw_extra(raw, self._EXTRACTED_KEYS),
            },
            "severity": raw.get("severity", "high"),
            "host_id": raw.get("host_id", 0),
        }


class BehaviorMapper(BaseMapper):
    """行为告警映射器: behavior_alert."""

    event_types = ["behavior_alert"]
    _EXTRACTED_KEYS = {
        "event_type", "rule_name", "rule_label", "reason", "severity",
        "source_process", "source_pid", "detail", "timestamp",
        "source_collector", "host_id",
    }

    def map(self, raw: dict) -> dict | None:
        return {
            "event_type": "behavior_alert",
            "event_key": raw.get("rule_name", raw.get("reason", "alert")),
            "timestamp": raw.get("timestamp", raw.get("_fallback_ts", datetime.now(timezone.utc).isoformat())),
            "source_collector": raw.get("source_collector", "behavior_engine"),
            "evidence": {
                "rule_name": raw.get("rule_name"),
                "rule_label": raw.get("rule_label"),
                "reason": raw.get("reason"),
                "severity": raw.get("severity"),
                "source_process": raw.get("source_process"),
                "source_pid": raw.get("source_pid"),
                "detail": raw.get("detail"),
                "_raw_extra": _compute_raw_extra(raw, self._EXTRACTED_KEYS),
            },
            "severity": raw.get("severity", "high"),
            "host_id": raw.get("host_id", 0),
        }


class IocMapper(BaseMapper):
    """IOC 命中映射器: ioc_match."""

    event_types = ["ioc_match"]
    _EXTRACTED_KEYS = {
        "event_type", "ioc_type", "ioc_value", "matched_field", "matched_context",
        "source", "ioc_matches", "matched_iocs", "timestamp", "source_collector",
        "severity", "host_id",
    }

    def map(self, raw: dict) -> dict | None:
        matches = raw.get("ioc_matches", raw.get("matched_iocs", []))
        if isinstance(matches, str):
            matches = [matches]
        return {
            "event_type": "ioc_match",
            "event_key": "_".join(matches) if matches else raw.get("ioc_value", "ioc"),
            "timestamp": raw.get("timestamp", raw.get("_fallback_ts", datetime.now(timezone.utc).isoformat())),
            "source_collector": raw.get("source_collector", "ioc_engine"),
            "evidence": {
                "ioc_type": raw.get("ioc_type"),
                "ioc_value": raw.get("ioc_value"),
                "matched_field": raw.get("matched_field"),
                "matched_context": raw.get("matched_context"),
                "source": raw.get("source"),
                "_raw_extra": _compute_raw_extra(raw, self._EXTRACTED_KEYS),
            },
            "ioc_matches": matches,
            "severity": "critical",
            "host_id": raw.get("host_id", 0),
        }


class AuthMapper(BaseMapper):
    """认证事件映射器: user_login / user_logout."""

    event_types = ["user_login", "user_logout"]
    _EXTRACTED_KEYS = {
        "event_type", "user_name", "username", "user_domain", "logon_type",
        "source_ip", "logon_session", "process_name", "timestamp",
        "source_collector", "severity", "host_id",
    }

    def map(self, raw: dict) -> dict | None:
        return {
            "event_type": raw.get("event_type", "user_login"),
            "event_key": raw.get("user_name", raw.get("username", "unknown")),
            "timestamp": raw.get("timestamp", raw.get("_fallback_ts", datetime.now(timezone.utc).isoformat())),
            "source_collector": raw.get("source_collector", "osquery"),
            "evidence": {
                "user_name": raw.get("user_name", raw.get("username")),
                "user_domain": raw.get("user_domain"),
                "logon_type": raw.get("logon_type"),
                "source_ip": raw.get("source_ip"),
                "logon_session": raw.get("logon_session"),
                "process_name": raw.get("process_name"),
                "_raw_extra": _compute_raw_extra(raw, self._EXTRACTED_KEYS),
            },
            "severity": raw.get("severity", "low"),
            "host_id": raw.get("host_id", 0),
        }


class ModuleMapper(BaseMapper):
    """模块加载映射器: module_load / driver_load."""

    event_types = ["module_load", "driver_load"]
    _EXTRACTED_KEYS = {
        "event_type", "module_name", "file_name", "file_path", "sha256",
        "pid", "process_name", "is_signed", "signer", "timestamp",
        "source_collector", "severity", "host_id",
    }

    def map(self, raw: dict) -> dict | None:
        return {
            "event_type": raw.get("event_type", "module_load"),
            "event_key": raw.get("file_path", raw.get("module_name", "")),
            "timestamp": raw.get("timestamp", raw.get("_fallback_ts", datetime.now(timezone.utc).isoformat())),
            "source_collector": raw.get("source_collector", "osquery"),
            "evidence": {
                "module_name": raw.get("module_name", raw.get("file_name")),
                "file_path": raw.get("file_path"),
                "sha256": raw.get("sha256"),
                "pid": raw.get("pid"),
                "process_name": raw.get("process_name"),
                "is_signed": raw.get("is_signed"),
                "signer": raw.get("signer"),
                "_raw_extra": _compute_raw_extra(raw, self._EXTRACTED_KEYS),
            },
            "severity": raw.get("severity", "medium"),
            "host_id": raw.get("host_id", 0),
        }


class PipeMapper(BaseMapper):
    """管道连接映射器: pipe_connect."""

    event_types = ["pipe_connect"]
    _EXTRACTED_KEYS = {
        "event_type", "pipe_name", "process_name", "pid", "timestamp",
        "source_collector", "severity", "host_id",
    }

    def map(self, raw: dict) -> dict | None:
        return {
            "event_type": "pipe_connect",
            "event_key": raw.get("pipe_name", ""),
            "timestamp": raw.get("timestamp", raw.get("_fallback_ts", datetime.now(timezone.utc).isoformat())),
            "source_collector": raw.get("source_collector", "osquery"),
            "evidence": {
                "pipe_name": raw.get("pipe_name"),
                "process_name": raw.get("process_name"),
                "pid": raw.get("pid"),
                "_raw_extra": _compute_raw_extra(raw, self._EXTRACTED_KEYS),
            },
            "severity": raw.get("severity", "medium"),
            "host_id": raw.get("host_id", 0),
        }


# ── 映射器注册表 ──

_MAPPERS: list[BaseMapper] = [
    ProcessMapper(),
    NetworkMapper(),
    RegistryMapper(),
    FileMapper(),
    PersistenceMapper(),
    WmiMapper(),
    BehaviorMapper(),
    IocMapper(),
    AuthMapper(),
    ModuleMapper(),
    PipeMapper(),
]

_TYPE_MAPPER_INDEX: dict[str, BaseMapper] = {}
for _mapper in _MAPPERS:
    for _et in _mapper.event_types:
        _TYPE_MAPPER_INDEX[_et] = _mapper


# ===================================================================
#  归一化管道
# ===================================================================


def validate_schema(raw: dict) -> tuple[bool, str]:
    """校验原始数据必填字段，缺失则降级记录但不阻断.

    Returns:
        (is_valid, error_message): error_message 仅在 is_valid=False 时有意义.
    """
    if not isinstance(raw, dict):
        return False, "原始数据不是 JSON 对象"
    if "event_type" not in raw:
        return False, "缺少 event_type 字段"
    if raw.get("event_type") not in EVENT_TYPES:
        return False, f"未知 event_type: {raw.get('event_type')}"
    required = ["host_id", "timestamp"]
    missing = [f for f in required if f not in raw and f not in raw]
    if missing:
        # 可选降级：缺失字段用默认值填充
        pass
    return True, ""


# 必填证据字段（按 event_type 分组）
_REQUIRED_EVIDENCE_FIELDS: dict[str, list[str]] = {
    "process_start": ["process_name"],
    "process_terminate": ["process_name"],
    "network_outbound": ["remote_address"],
    "dns_query": ["query"],
    "registry_modify": ["key_path"],
    "file_create": ["file_name"],
}


def _check_field_quality(fields: dict) -> list[str]:
    """检查映射后字段质量，返回 quality_flags 列表.

    每个 flag 标记一个可修复的缺失项，不会阻断归一化。
    """
    flags: list[str] = []
    event_type = fields.get("event_type", "")
    evidence = fields.get("evidence")
    if not isinstance(evidence, dict):
        evidence = {}

    # 1. 必填证据字段检查
    for required_field in _REQUIRED_EVIDENCE_FIELDS.get(event_type, []):
        if required_field not in evidence or evidence.get(required_field) in (None, "", []):
            flags.append(f"missing_evidence_field:{required_field}")

    # 2. severity 合理性
    sev = fields.get("severity", "")
    if sev and sev not in ("critical", "high", "medium", "low", "info"):
        flags.append(f"invalid_severity:{sev}")

    # 3. 主机 ID
    if not fields.get("host_id"):
        flags.append("missing_host_id")

    return flags


def normalize_single(raw: dict, validate: bool = True) -> SecurityEvent | None:
    """将单条 Agent 原始数据归一化为 SecurityEvent.

    Args:
        raw: Agent 上报的原始数据字典.
        validate: 是否执行逐字段校验并打 quality_flags.

    Returns:
        SecurityEvent 实例，或 None（映射失败跳过）.
    """
    # 1. Schema 校验
    valid, err = validate_schema(raw)
    if not valid:
        logger.warning("归一化跳过: %s, raw=%s", err, json.dumps(raw, ensure_ascii=False)[:200])
        return None

    event_type = raw["event_type"]

    # 2. 类型路由 → 映射器
    mapper = _TYPE_MAPPER_INDEX.get(event_type)
    if mapper is None:
        logger.warning("未找到 event_type=%s 的映射器, raw=%s", event_type, json.dumps(raw, ensure_ascii=False)[:200])
        return None

    fields = mapper.map(raw)
    if fields is None:
        return None

    # 3. 逐字段校验 (validate=True 时)
    quality_flags: list[str] = []
    if validate:
        quality_flags = _check_field_quality(fields)

    # 4. 生成唯一 ID
    fields["event_key"] = fields.get("event_key", str(raw.get("timestamp", "")))
    host_id = fields.get("host_id", 0)
    event_id = make_event_id(host_id, event_type, fields["event_key"])
    fields["id"] = event_id

    # 5. ATT&CK 阶段分类
    fields["attack_stage"] = infer_attack_stage(event_type, fields.get("evidence"))

    # 6. 质量标记注入 evidence
    evidence = fields.get("evidence")
    if isinstance(evidence, dict) and quality_flags:
        evidence_copy = dict(evidence)
        evidence_copy["_quality_flags"] = quality_flags
        fields["evidence"] = evidence_copy
    elif not isinstance(evidence, dict):
        fields["evidence"] = {"_quality_flags": quality_flags} if quality_flags else {}

    # 7. 构建 SecurityEvent
    event = SecurityEvent(**fields)

    # 6. 确保基本字段
    if not event.timestamp:
        event.timestamp = datetime.now(timezone.utc).isoformat()
    if not event.created_at:
        event.created_at = event.timestamp
    if not event.updated_at:
        event.updated_at = event.timestamp

    # IOC 匹配列表同步
    if event_type == "ioc_match" and not event.ioc_matches:
        ioc_val = raw.get("ioc_value")
        if ioc_val:
            event.ioc_matches = [ioc_val]

    return event


def normalize_batch(raw_events: list[dict], validate: bool = True) -> list[SecurityEvent]:
    """批量归一化 20+ 类 Agent 原始数据.

    Args:
        raw_events: Agent 原始数据列表.
        validate: 是否执行逐字段校验并打 quality_flags（§4.2 Schema 校验）.

    Returns:
        归一化后的 SecurityEvent 列表（映射失败的数据已过滤）.
    """
    normalized: list[SecurityEvent] = []
    for raw in raw_events:
        try:
            event = normalize_single(raw, validate=validate)
            if event is not None:
                normalized.append(event)
        except Exception as exc:
            logger.exception("归一化异常: %s, raw=%s", exc, json.dumps(raw, ensure_ascii=False)[:200])
    return normalized


# ===================================================================
#  批量写入（幂等去重）
# ===================================================================


def bulk_insert(events: list[SecurityEvent]) -> tuple[int, int]:
    """批量写入事件到 security_events 表（幂等去重）.

    Args:
        events: SecurityEvent 实例列表.

    Returns:
        (inserted_count, skipped_count).
    """
    if not events:
        return 0, 0

    import sqlite3

    inserted = 0
    skipped = 0

    with get_connection() as conn:
        conn.execute("BEGIN")  # 显式事务：批量 INSERT 合并为一次提交
        for event in events:
            try:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO security_events
                        (id, timestamp, host_id, event_type, severity,
                         source_collector, event_key, attack_chain_id, attack_stage,
                         ioc_matches, evidence, status, assignee, related_events,
                         matched_rules, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.id,
                        event.timestamp,
                        event.host_id,
                        event.event_type,
                        event.severity,
                        event.source_collector,
                        event.event_key,
                        event.attack_chain_id,
                        event.attack_stage,
                        json.dumps(event.ioc_matches, ensure_ascii=False),
                        json.dumps(event.evidence, ensure_ascii=False),
                        event.status,
                        event.assignee,
                        json.dumps(event.related_events, ensure_ascii=False),
                        json.dumps(event.matched_rules, ensure_ascii=False),
                        event.created_at,
                        event.updated_at,
                    ),
                )
                if conn.total_changes > 0:
                    inserted += 1
                else:
                    skipped += 1
            except sqlite3.IntegrityError:
                skipped += 1
            except Exception as exc:
                logger.warning("写入事件失败: %s, id=%s", exc, event.id)
                skipped += 1

    logger.info("批量写入完成: inserted=%d, skipped=%d", inserted, skipped)
    return inserted, skipped


# ===================================================================
#  规则匹配增强
# ===================================================================


def _enrich_with_matched_rules(events: list[SecurityEvent]) -> None:
    """对事件列表执行规则匹配，填充 matched_rules 字段."""
    from app.services.rule_matcher import match_event

    for event in events:
        try:
            event_dict = {
                "id": event.id,
                "event_type": event.event_type,
                "severity": event.severity,
                "evidence": event.evidence,
                "host_id": event.host_id,
            }
            matched = match_event(event_dict)
            if matched:
                event.matched_rules = matched
        except Exception as exc:
            logger.warning("规则匹配异常: %s, event_id=%s", exc, event.id)


# ===================================================================
#  Ingest 入口（便捷批量接口）
# ===================================================================


def ingest_events(raw_events: list[dict]) -> dict:
    """接收 Agent 原始数据 -> 归一化 -> 规则匹配 -> 批量写入.

    Args:
        raw_events: Agent 原始数据列表.

    Returns:
        { ingested_count, skipped_count }.
    """
    normalized = normalize_batch(raw_events)
    # 规则匹配增强
    _enrich_with_matched_rules(normalized)
    inserted, skipped = bulk_insert(normalized)
    total_skipped = len(raw_events) - len(normalized) + skipped
    return {
        "ingested_count": inserted,
        "skipped_count": total_skipped,
    }
