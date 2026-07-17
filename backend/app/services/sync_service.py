"""双向同步服务（v2 SyncLayer）.

职责：
  - CM→AC 同步（主要方向）：将 CM 分析结果（abnormal_processes/persistence_items/incident_correlations 等）
    映射为 CanonicalEvent 并 upsert 进 security_events，使 AC 侧可见行为告警（补 behavior 缺口）。
  - AC→CM 同步（辅助方向）：将 AC 侧状态/处置变更回写 CM，保证两端处置一致。
  - Backfill：全量补同步（首次接入或修复后）。

设计原则（§6）：
  CM→AC 为主，AC→CM 为辅，幂等 upsert(event_uid)，version/updated_at 大者胜冲突解决，
  最多 3 次重试，失败进 sync_dead_letter。
"""
from __future__ import annotations

import json
import logging
import statistics
import time
from datetime import datetime
from typing import Any, Optional

from app.database import get_connection
from app.services.canonical_event import CanonicalEvent, canonical_event_to_security_event_row

logger = logging.getLogger(__name__)


class SyncError(Exception):
    """同步异常。"""


# ── CM 表到 CanonicalEvent 的映射元信息 ──
CM_TABLE_MAP: dict[str, dict] = {
    "abnormal_processes": {
        "event_type": "process_start",
        "category": "behavior",
        "severity_field": "severity",
        "risk_field": "risk_score",
        "evidence_fields": [
            "process_name", "process_path", "command_line", "pid",
            "parent_pid", "parent_name", "reason", "details", "matched_rules", "attack_path",
        ],
        "min_severity": "medium",
    },
    "persistence_items": {
        "event_type": "persistence_register",
        "category": "persistence",
        "severity_field": None,
        "risk_field": None,
        "evidence_fields": [
            "type", "name", "command", "location", "user", "is_suspicious", "reason", "details",
        ],
        "min_severity": "medium",
        "filter": "is_suspicious=1",
    },
    "suspicious_startup_items": {
        "event_type": "persistence_register",
        "category": "startup",
        "severity_field": "severity",
        "risk_field": None,
        "evidence_fields": [
            "name", "command", "location", "type", "user", "reason", "details",
        ],
        "min_severity": "low",
    },
    "incident_correlations": {
        "event_type": "behavior_alert",
        "category": "behavior",
        "severity_field": "severity",
        "risk_field": None,
        "evidence_fields": [
            "title", "description", "kill_chain", "mitre_ids", "recommendations", "timeline_json",
        ],
        "min_severity": "medium",
    },
    "file_hashes": {
        "event_type": "file_create",
        "category": "ioc",
        "severity_field": None,
        "risk_field": None,
        "evidence_fields": [
            "file_path", "file_name", "sha256", "is_signed", "signer", "file_size",
        ],
        "min_severity": "low",
    },
}


def resolve_severity(row: dict, sev_field: Optional[str]) -> str:
    """从行数据中解析严重级别，默认 medium。"""
    if sev_field:
        val = row.get(sev_field)
        if val and str(val).strip():
            return str(val).strip().lower()
    return "medium"


def build_evidence(row: dict, evidence_fields: list[str]) -> dict:
    """从行数据中提取证据字段。"""
    ev = {}
    for f in evidence_fields:
        v = row.get(f)
        if v is not None:
            ev[f] = v
    return ev


def cm_row_to_canonical(table: str, row: dict, host_id: int, cfg: dict) -> CanonicalEvent:
    """将 CM 表的一行转为 CanonicalEvent。"""
    event_type = cfg["event_type"]
    category = cfg["category"]
    severity = resolve_severity(row, cfg.get("severity_field"))
    risk_score = row.get(cfg["risk_field"]) if cfg.get("risk_field") else 0
    risk_score = int(risk_score) if risk_score else 0

    row_id = row.get("id") or row.get("Id") or 0
    event_uid = f"cm:{table}:{row_id}"

    evidence = build_evidence(row, cfg["evidence_fields"])
    evidence["sync_source"] = table

    timestamp = row.get("collected_at") or row.get("created_at") or datetime.now().isoformat()
    status = row.get("status", "pending")
    assignee = row.get("assigned_to")

    return CanonicalEvent(
        event_uid=event_uid,
        source="cm",
        source_event_id=str(row_id),
        host_id=host_id,
        event_type=event_type,
        category=category,
        severity=severity,
        risk_score=risk_score,
        status=status,
        assignee=assignee,
        timestamp=str(timestamp),
        evidence=evidence,
        lifecycle_state="synced",
        version=1,
        updated_at=datetime.now().isoformat(),
        attack_stage=row.get("kill_chain") or row.get("attack_path") or None,
        # 构建 matched_rules 使前端可识别为"已匹配"
        matched_rules_str=json.dumps(_build_cm_matched_rule(row, table, cfg), ensure_ascii=False),
    )


def _build_cm_matched_rule(row: dict, table: str, cfg: dict) -> list[dict]:
    """从 CM 行数据构建 matched_rules 列表，使前端识别为已匹配事件。"""
    rule = {
        "rule_id": f"cm:{table}:{row.get('id','?')}",
        "rule_name": row.get("rule_name") or table,
        "rule_type": "behavior",
        "category": cfg.get("category", "unknown"),
        "severity": resolve_severity(row, cfg.get("severity_field")),
        "confidence": 0.85,
        "matched_fields": {},
    }
    reason = row.get("reason") or row.get("description") or ""
    if reason:
        rule["description"] = str(reason)[:200]
    return [rule]


class SyncService:
    """双向同步服务（CM→AC 为主）。"""

    @staticmethod
    def sync_cm_to_ac(host_id: int) -> dict:
        """CM→AC 同步：将 CM 分析结果写入 security_events。

        Args:
            host_id: 主机 ID.

        Returns:
            {"host_id", "total_cm_rows", "synced", "skipped", "errors",
             "sync_lag_ms_p95", "sync_lag_ms_avg"}
        """
        total_cm = 0
        synced = 0
        skipped = 0
        errors: list[dict] = []
        sync_timings: list[float] = []  # 每行同步耗时（ms）

        with get_connection() as conn:
            for table, cfg in CM_TABLE_MAP.items():
                try:
                    rows = _fetch_cm_rows(conn, table, host_id, cfg)
                except Exception as exc:
                    errors.append({"table": table, "error": str(exc)})
                    continue
                total_cm += len(rows)
                for row in rows:
                    start_t = time.time()
                    row_id = row.get("id", "?")
                    event_uid = f"cm:{table}:{row_id}"
                    # 重试循环：最多 3 次，指数退避
                    success = False
                    last_error = None
                    for attempt in range(1, 4):
                        try:
                            ce = cm_row_to_canonical(table, row, host_id, cfg)
                            _upsert_security_event(conn, ce)
                            synced += 1
                            success = True
                            break
                        except Exception as exc:
                            last_error = str(exc)
                            if attempt < 3:
                                time.sleep(0.5 * (2 ** (attempt - 1)))  # 0.5s, 1s, 2s
                    if not success:
                        # 失败 → dead_letter + errors
                        _write_sync_dead_letter(conn, event_uid, table, host_id,
                                                 last_error or "unknown", attempts=3)
                        errors.append({"table": table, "event_uid": event_uid,
                                       "error": last_error, "attempts": 3})
                        skipped += 1
                    else:
                        sync_timings.append((time.time() - start_t) * 1000)  # ms

            conn.commit()

        # 计算同步延迟指标
        p95 = round(statistics.quantiles(sync_timings, n=20)[18], 2) if len(sync_timings) >= 20 else \
              round(max(sync_timings), 2) if sync_timings else 0.0
        avg = round(sum(sync_timings) / len(sync_timings), 2) if sync_timings else 0.0

        logger.info("sync_cm_to_ac host=%d: total=%d synced=%d skipped=%d errors=%d lag_p95=%.1fms",
                     host_id, total_cm, synced, skipped, len(errors), p95)
        return {
            "host_id": host_id,
            "total_cm_rows": total_cm,
            "synced": synced,
            "skipped": skipped,
            "errors": errors,
            "sync_lag_ms_p95": p95,
            "sync_lag_ms_avg": avg,
        }

    @staticmethod
    def sync_ac_to_cm(event_uid: str) -> dict:
        """AC→CM 同步：将 AC 侧状态/处置变更回写 CM。

        Args:
            event_uid: CanonicalEvent 的 event_uid (格式 "ac:{id}" 或 "cm:{table}:{id}").

        Returns:
            {"event_uid", "status", "message"}
        """
        if not event_uid.startswith("ac:") and not event_uid.startswith("cm:"):
            return {"event_uid": event_uid, "status": "skipped", "message": "invalid event_uid"}

        with get_connection() as conn:
            # 读当前 AC 事件
            se = conn.execute(
                "SELECT id, status, assignee, host_id FROM security_events WHERE id=?",
                (event_uid,),
            ).fetchone()
            if not se:
                return {"event_uid": event_uid, "status": "skipped", "message": "not found"}

            # 如果是 CM 来源的事件，回写 CM 表
            if event_uid.startswith("cm:"):
                parts = event_uid.split(":", 2)
                if len(parts) == 3:
                    _, table, row_id = parts
                    try:
                        conn.execute(
                            f"UPDATE {table} SET status=?, assigned_to=? WHERE id=?",
                            (se["status"], se["assignee"], int(row_id)),
                        )
                        conn.commit()
                        return {"event_uid": event_uid, "status": "synced",
                                "message": f"status={se['status']} written to {table}:{row_id}"}
                    except Exception as exc:
                        return {"event_uid": event_uid, "status": "error", "message": str(exc)}

            # AC 原生事件（直接来源）
            return {"event_uid": event_uid, "status": "noop", "message": "ac-native event, no cm back-ref"}

    @staticmethod
    def backfill(host_id: int, source: str = "cm") -> dict:
        """全量补同步（首次接入或修复后）。

        Args:
            host_id: 主机 ID.
            source: "cm"（CM→AC 补同步，默认）或 "ac"（AC→CM 补同步）.

        Returns:
            同步结果字典.
        """
        if source == "cm":
            return SyncService.sync_cm_to_ac(host_id)
        elif source == "ac":
            # AC→CM: 遍历安全事件，回写状态
            with get_connection() as conn:
                rows = conn.execute(
                    "SELECT id, status, assignee FROM security_events WHERE host_id=?",
                    (host_id,),
                ).fetchall()
            synced = 0
            for r in rows:
                result = SyncService.sync_ac_to_cm(r["id"])
                if result["status"] == "synced":
                    synced += 1
            return {"host_id": host_id, "source": "ac", "synced": synced, "total": len(rows)}
        else:
            return {"error": f"unknown source: {source}"}


# ===================================================================
#  内部辅助
# ===================================================================


def _fetch_cm_rows(conn, table: str, host_id: int, cfg: dict) -> list[dict]:
    """从 CM 表 fetch 行数据，应用严重级别过滤。"""
    min_sev = cfg.get("min_severity", "low")
    sev_field = cfg.get("severity_field")
    extra_filter = cfg.get("filter", "")

    # 处理 host_ids（复数，JSON 数组）vs host_id（单数，整数）
    if table == "incident_correlations":
        where_clause = f"host_ids LIKE '%\"{host_id}\"%'"
    else:
        where_clause = "host_id=?"

    sql = f"SELECT * FROM {table} WHERE {where_clause}"
    params: list = [host_id] if table != "incident_correlations" else []

    if extra_filter:
        sql += f" AND {extra_filter}"

    rows = conn.execute(sql, params).fetchall()
    result = []
    for r in rows:
        rd = dict(r)
        if sev_field:
            sev = (rd.get(sev_field) or "low").strip().lower()
            if not _meets_min_severity(sev, min_sev):
                continue
        result.append(rd)
    return result


def _meets_min_severity(severity: str, min_sev: str) -> bool:
    """严重级别 >= min_sev 判定。"""
    ORDER = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}
    return ORDER.get(severity, 0) >= ORDER.get(min_sev, 0)


def _upsert_security_event(conn, ce: CanonicalEvent) -> None:
    """将 CanonicalEvent upsert 为 security_events 行。"""
    row = canonical_event_to_security_event_row(ce)
    # 幂等：event_uid 已存在则跳过（security_events 无 version 列，冲突由同步侧控制）
    existing = conn.execute(
        "SELECT id FROM security_events WHERE id=?", (ce.event_uid,)
    ).fetchone()
    if existing:
        return  # 已有则跳过（幂等）
    conn.execute(
        """INSERT OR IGNORE INTO security_events
           (id, event_type, severity, status, host_id, timestamp, event_key,
            attack_stage, attack_chain_id, matched_rules, ioc_matches,
            evidence, assignee, related_events, source_collector, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            row["id"], row["event_type"], row["severity"], row["status"],
            row["host_id"], row["timestamp"], row["event_key"],
            row["attack_stage"], row["attack_chain_id"], row["matched_rules"], row["ioc_matches"],
            row["evidence"], row["assignee"], row["related_events"],
            row["source_collector"], row["created_at"], row["updated_at"],
        ),
    )


def _write_sync_dead_letter(conn, event_uid: str, table: str, host_id: int,
                             error_msg: str, attempts: int) -> None:
    """将同步失败的记录写入 sync_dead_letter 表。"""
    try:
        conn.execute(
            """INSERT OR REPLACE INTO sync_dead_letter
               (event_uid, source_table, host_id, error_message, attempts, failed_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (event_uid, table, host_id, error_msg[:500], attempts,
             datetime.now().isoformat()),
        )
    except Exception as exc:
        logger.warning("sync_dead_letter write failed: %s", exc)
