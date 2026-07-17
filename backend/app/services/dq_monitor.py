"""数据质量监控服务（v2.1 DQMonitor 模块）.

职责：监控分析中心事件数据的质量指标，尤其**必填展示字段的填充率**，
保障"前端首屏必有决策信息"这一应急底线（详见 analysis_center_optimization_design.md §7）。

监控指标：
  - field_fill_rate：必填展示字段（§10 标注「必填」者）非空比例。
  - 同步延迟 / 覆盖率 / 命中率 / 两端对账 等由 SyncLayer 另外提供，本模块聚焦字段质量。
"""

from __future__ import annotations

import json
import logging
import os
from collections import Counter
from typing import Any, Optional

from app.database import get_connection
from app.services.canonical_event import CanonicalEvent

logger = logging.getLogger(__name__)


# ── 确保 DQ 辅助表存在（§4.2 死信表、导入异常表）────────────────────
def _ensure_dq_tables():
    """确保数据质量监控所需的辅助表存在（幂等）。"""
    from app.database import get_connection as _db
    try:
        with _db() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS import_anomalies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    host_id INTEGER,
                    import_id INTEGER,
                    anomaly_type TEXT,
                    expected_count INTEGER,
                    actual_count INTEGER,
                    raw_block TEXT,
                    detail TEXT,
                    created_at TEXT DEFAULT (datetime('now'))
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS raw_failed (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    host_id INTEGER,
                    file_name TEXT,
                    raw_json TEXT,
                    error_type TEXT,
                    error_message TEXT,
                    created_at TEXT DEFAULT (datetime('now'))
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sync_dead_letter (
                    event_uid TEXT PRIMARY KEY,
                    source_table TEXT,
                    host_id INTEGER,
                    error_message TEXT,
                    attempts INTEGER DEFAULT 1,
                    recovered INTEGER DEFAULT 0,
                    failed_at TEXT,
                    recovered_at TEXT
                )
            """)
            conn.commit()
            logger.info("DQ auxiliary tables ensured (import_anomalies, raw_failed, sync_dead_letter)")
    except Exception as exc:
        logger.warning("DQ table init non-critical: %s", exc)


_ensure_dq_tables()


# 必填展示字段中，需在数据源中真实存在、可能缺失的字段（用于填充率统计）。
# 结构性字段（id/时间戳/摘要/风险评分/分类 等由投影层保证）不计入缺失统计。
SOURCE_REQUIRED_FIELDS: list[str] = [
    "event_type",
    "attack_stage",
    "severity",
    "status",
    "matched_rules",   # 已匹配事件须非空（matched_rules != '[]'）
    "attack_chain_id", # 关联攻击链（attack_chain_id 或 related_events 非空）
    "ioc_matches",     # 情报命中（非空即算）
]


def _row_fills(row: dict) -> dict[str, bool]:
    """判断单行各必填源字段是否非空。"""
    fills: dict[str, bool] = {}
    matched = row.get("matched_rules")
    try:
        matched_list = json.loads(matched) if isinstance(matched, str) else (matched or [])
    except (json.JSONDecodeError, TypeError):
        matched_list = []
    ioc = row.get("ioc_matches")
    try:
        ioc_list = json.loads(ioc) if isinstance(ioc, str) else (ioc or [])
    except (json.JSONDecodeError, TypeError):
        ioc_list = []
    related = row.get("related_events")
    try:
        related_list = json.loads(related) if isinstance(related, str) else (related or [])
    except (json.JSONDecodeError, TypeError):
        related_list = []

    fills["event_type"] = bool(row.get("event_type"))
    fills["attack_stage"] = bool(row.get("attack_stage"))
    fills["severity"] = bool(row.get("severity"))
    fills["status"] = bool(row.get("status"))
    fills["matched_rules"] = len(matched_list) > 0
    fills["attack_chain_id"] = bool(row.get("attack_chain_id")) or len(related_list) > 0
    fills["ioc_matches"] = len(ioc_list) > 0
    return fills


def check_field_fill(host_id: int) -> dict:
    """检查指定主机必填展示字段的填充率（§10 必填项）。

    Returns:
        {
          "host_id": int,
          "total_events": int,
          "fields": { field: {"filled": int, "total": int, "rate": float} },
          "overall_rate": float,
          "events_with_missing": int,
        }
    """
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT event_type, attack_stage, severity, status, matched_rules, "
            "attack_chain_id, related_events, ioc_matches "
            "FROM security_events WHERE host_id = ?",
            (host_id,),
        ).fetchall()

    total = len(rows)
    counters: dict[str, int] = {f: 0 for f in SOURCE_REQUIRED_FIELDS}
    events_with_missing = 0

    for r in rows:
        fills = _row_fills(dict(r))
        row_ok = True
        for f in SOURCE_REQUIRED_FIELDS:
            if fills[f]:
                counters[f] += 1
            else:
                row_ok = False
        if not row_ok:
            events_with_missing += 1

    fields_detail = {}
    for f in SOURCE_REQUIRED_FIELDS:
        filled = counters[f]
        fields_detail[f] = {
            "filled": filled,
            "total": total,
            "rate": round(filled / total, 4) if total else 1.0,
        }
    overall = round(sum(counters.values()) / (total * len(SOURCE_REQUIRED_FIELDS)), 4) if total else 1.0

    return {
        "host_id": host_id,
        "total_events": total,
        "fields": fields_detail,
        "overall_rate": overall,
        "events_with_missing": events_with_missing,
    }


def get_metrics() -> dict:
    """全局数据质量指标（含必填字段填充率）."""
    with get_connection() as conn:
        total = conn.execute("SELECT COUNT(*) as c FROM security_events").fetchone()["c"]
        total_hosts = conn.execute("SELECT COUNT(DISTINCT host_id) as c FROM security_events").fetchone()["c"]

    # 聚合所有主机的字段填充（一次性扫描）
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT event_type, attack_stage, severity, status, matched_rules, "
            "attack_chain_id, related_events, ioc_matches FROM security_events"
        ).fetchall()

    total = len(rows)
    counters = {f: 0 for f in SOURCE_REQUIRED_FIELDS}
    for r in rows:
        fills = _row_fills(dict(r))
        for f in SOURCE_REQUIRED_FIELDS:
            if fills[f]:
                counters[f] += 1

    fields_detail = {
        f: {"filled": counters[f], "total": total,
            "rate": round(counters[f] / total, 4) if total else 1.0}
        for f in SOURCE_REQUIRED_FIELDS
    }
    overall = round(sum(counters.values()) / (total * len(SOURCE_REQUIRED_FIELDS)), 4) if total else 1.0

    return {
        "total_events": total,
        "total_hosts": total_hosts,
        "required_field_fill": fields_detail,
        "overall_required_fill_rate": overall,
    }


# ===================================================================
#  DQReconciler 类（v2 §3/§7 全量质量监控）
# ===================================================================

# 原始 JSON 中预期存在的顶层区块（用于覆盖率校验）
EXPECTED_RAW_BLOCKS: list[str] = [
    "processes", "network_connections", "registry_keys", "file_hashes", "files",
    "persistence", "startup_items", "services", "users", "wmi_subscriptions",
    "logs", "security", "browser", "usb", "remote_control", "ioc", "timeline",
    "network", "registry", "system_info", "metadata",
]

# AC 当前已映射的原始键 → event_type
AC_MAPPED_BLOCKS: dict[str, str] = {
    "processes": "process_start",
    "network_connections": "network_outbound",
    "registry_keys": "registry_modify",
    "file_hashes": "file_create",
    "files": "file_event",
    "logs": "log_event",
    "security": "security_event",
    "browser": "browser_event",
    "usb": "usb_event",
    "remote_control": "remote_control_event",
    "ioc": "ioc_event",
    "services": "service_operation",
    "users": "user_login",
    "wmi_subscriptions": "wmi_subscribe",
    "startup_items": "persistence_register",
}


class DQReconciler:
    """数据质量监控与一致性对账（v2 §7 全量接口）。

    四大方法对应 §3 DQReconciler 接口 + §7 的全维度监控。
    """

    @staticmethod
    def check_coverage(host_id: int) -> dict:
        """检查指定主机的原始数据覆盖率（§7 coverage_rate）。

        对比原始 JSON 顶层区块 与 AC 已入表区块。

        Returns:
            {"host_id", "total_blocks", "covered_blocks", "coverage_rate",
             "mapped_blocks": [...], "unmapped_blocks": [...],
             "ac_events_per_block": {...}}
        """
        from app.services.import_service import ImportService

        raw = ImportService.read_raw_json(host_id)
        if not raw:
            return {"host_id": host_id, "error": "raw_json not found"}

        # 原始 JSON 中存在的区块
        present_blocks = [k for k in EXPECTED_RAW_BLOCKS if k in raw]
        total = len(present_blocks)

        # 已覆盖（在 AC_MAPPED_BLOCKS 中）
        covered = [b for b in present_blocks if b in AC_MAPPED_BLOCKS]
        uncovered = [b for b in present_blocks if b not in AC_MAPPED_BLOCKS]
        coverage_rate = round(len(covered) / total, 4) if total else 1.0

        # AC 每个 block 对应事件数
        with get_connection() as conn:
            event_counts = {}
            for block, etype in AC_MAPPED_BLOCKS.items():
                cnt = conn.execute(
                    "SELECT COUNT(*) as c FROM security_events WHERE host_id=? AND event_type=?",
                    (host_id, etype),
                ).fetchone()["c"]
                event_counts[block] = cnt

        return {
            "host_id": host_id,
            "total_blocks": total,
            "covered_blocks": len(covered),
            "coverage_rate": coverage_rate,
            "mapped_blocks": covered,
            "unmapped_blocks": uncovered,
            "ac_events_per_block": event_counts,
            "expected_coverage_target": 1.0,
            "alert": coverage_rate < 0.8,
        }

    @staticmethod
    def check_divergence(host_id: int) -> dict:
        """检查 AC vs CM 两端数据分歧（§7 divergence_count）。

        AC: security_events 事件数 for host.
        CM: CM 分析结果表（abnormal_processes/persistence_items 等）行数。

        Returns:
            {"host_id", "ac_event_count", "cm_row_count", "divergence", "detail": {...}}
        """
        with get_connection() as conn:
            # AC 端事件数
            ac_count = conn.execute(
                "SELECT COUNT(*) as c FROM security_events WHERE host_id=?", (host_id,)
            ).fetchone()["c"]

            # CM 端各表行数
            cm_tables = [
                "abnormal_processes",
                "persistence_items",
                "suspicious_startup_items",
                "file_hashes",
                "incident_correlations",
            ]
            cm_detail = {}
            cm_total = 0
            for tbl in cm_tables:
                try:
                    cnt = conn.execute(
                        f"SELECT COUNT(*) as c FROM {tbl} WHERE host_id=?", (host_id,)
                    ).fetchone()["c"]
                    cm_detail[tbl] = cnt
                    cm_total += cnt
                except Exception:
                    cm_detail[tbl] = 0

        # AC 事件中来自 CM 同步的事件数
        with get_connection() as conn:
            cm_sourced = conn.execute(
                "SELECT COUNT(*) as c FROM security_events WHERE host_id=? AND id LIKE 'cm:%'",
                (host_id,),
            ).fetchone()["c"]

        divergence = abs(ac_count - cm_total)
        return {
            "host_id": host_id,
            "ac_event_count": ac_count,
            "cm_total_rows": cm_total,
            "cm_detail": cm_detail,
            "divergence": divergence,
            "ac_cm_sourced_events": cm_sourced,
            "alert": divergence > 100,
        }

    @staticmethod
    def check_field_fill(host_id: int) -> dict:
        """检查必填展示字段填充率（§7/§10）。
        
        委托给顶级 check_field_fill 函数。
        """
        return check_field_fill(host_id)

    @staticmethod
    def metrics() -> dict:
        """全局质量指标聚合（含新增覆盖率/分歧/填充率）。

        Returns:
            {"total_events", "total_hosts", "coverage_rate", "divergence_count",
             "required_field_fill", "overall_required_fill_rate", "match_rate"}
        """
        base = get_metrics()
        # match_rate: 有 matched_rules 的事件比例
        with get_connection() as conn:
            total = conn.execute("SELECT COUNT(*) as c FROM security_events").fetchone()["c"]
            matched = conn.execute(
                "SELECT COUNT(*) as c FROM security_events WHERE matched_rules IS NOT NULL AND matched_rules != '[]'"
            ).fetchone()["c"]
        base["match_rate"] = round(matched / total, 4) if total else 0.0
        base["coverage_rate"] = None   # 需按 host 查询
        base["divergence_count"] = None
        # sync_lag_p95: 从最近同步记录中获取（当前无持久化历史，暂返回 None）
        base["sync_lag_p95"] = None
        return base
