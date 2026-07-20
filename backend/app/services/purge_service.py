"""清案（被遗忘权）核心清除服务.

提供：
- ``purge_case``        执行级联硬删 + 快照 + 审计（单事务原子）。
- ``preview_case_purge`` 预览清案影响面（各表预估行数）。
- 辅助函数 ``_resolve_case / _del / _snapshot / _write_data_purge_log / _write_audit_log``。

设计依据：docs/case_purge_design.md §3.3（删除顺序）、§3.9（事务）、
§3.11（决策点 3 按 id 精确解析 / 5 默认导出快照）。

安全要点：
1. 所有 SQL 均参数化；表名仅来自本模块白名单常量，不来自用户输入，可安全拼接。
2. 单连接 ``with get_connection()`` + ``BEGIN IMMEDIATE`` 写锁，要么全清要么全不清。
3. ``data_purge_log`` 与 ``audit_logs`` 永不参与清除（本服务不对这两张表执行 DELETE）。
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import HTTPException

from app.database import get_connection

logger = logging.getLogger(__name__)

# 快照落盘目录：backend/app/data/purge_snapshots/{case_id}_{timestamp}.json
SNAPSHOT_DIR: Path = Path(__file__).resolve().parent.parent / "data" / "purge_snapshots"


def _host_ph(host_ids: list) -> str:
    """生成 host_id IN (...) 占位符；空列表时返回 'NULL'（子查询不命中）。"""
    return ",".join("?" for _ in host_ids) or "NULL"


def _resolve_case(conn, case_id: int) -> Optional[dict]:
    """按 id 精确解析案件（决策点 3：不做模糊匹配）。"""
    row = conn.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
    return dict(row) if row else None


def _del(conn, sql: str, params) -> int:
    """执行一条 DELETE 并返回受影响行数。"""
    cur = conn.execute(sql, params)
    return cur.rowcount


def _iter_ops(host_ids: list, cid: int):
    """按 §3.3 顺序逐一产出 (表名, FROM 子句, 参数)。

    yield 的 ``FROM 子句`` 同时用于 SELECT COUNT(*) 与 DELETE，
    保证「预览计数」与「实际删除」使用完全相同的表集合与顺序。
    """
    ph = _host_ph(host_ids)
    # 1. 事件/安全子树（event_disposition_log 必须先于 security_events，否则外键冲突）
    yield ("event_disposition_log",
           f"FROM event_disposition_log WHERE event_id IN "
           f"(SELECT id FROM security_events WHERE host_id IN ({ph}))", host_ids)
    yield ("status_history",
           f"FROM status_history WHERE event_id IN "
           f"(SELECT id FROM security_events WHERE host_id IN ({ph}))", host_ids)
    yield ("security_events",
           f"FROM security_events WHERE host_id IN ({ph})", host_ids)
    # 2. AI 非外键 host 表
    for t in ("ai_audit_log", "ai_tasks", "agent_baselines", "ai_evidence_refills"):
        yield (t, f"FROM {t} WHERE host_id IN ({ph})", host_ids)
    # 3. host 外键级联表（显式删，主要为计数 + 兼容 FK 关闭场景）
    for t in (
        "import_records", "host_profiles", "analysis_results", "abnormal_processes",
        "suspicious_connections", "suspicious_startup_items", "persistence_items",
        "timeline_events", "ioc_hits", "network_connections", "file_hashes",
        "wmi_subscriptions", "registry_keys", "process_events", "webshells",
        "memory_shells", "agents", "normalized_logs",
    ):
        yield (t, f"FROM {t} WHERE host_id IN ({ph})", host_ids)
    # 4. 案件直辖表（按 case_id）
    for t in ("alerts", "agent_imports", "remediation_checklist", "ai_analysis_reports"):
        yield (t, f"FROM {t} WHERE case_id=?", (cid,))
    yield ("incident_reports", "FROM incident_reports WHERE case_id=?", (cid,))
    # 5. 根
    yield ("hosts", "FROM hosts WHERE case_id=?", (cid,))
    yield ("cases", "FROM cases WHERE id=?", (cid,))


def _preview_ordered(conn, host_ids: list, cid: int) -> dict:
    """按删除顺序统计各表预估删除行数。"""
    counts: dict = {}
    for name, frm, params in _iter_ops(host_ids, cid):
        cnt = conn.execute(f"SELECT COUNT(*) {frm}", params).fetchone()[0]
        counts[name] = cnt
    return counts


def _delete_ordered(conn, host_ids: list, cid: int) -> dict:
    """按 §3.3 顺序逐表删除，返回各表删除行数字典。"""
    counts: dict = {}
    for name, frm, params in _iter_ops(host_ids, cid):
        counts[name] = _del(conn, f"DELETE {frm}", params)
    return counts


def _snapshot(conn, cid: int, host_ids: list) -> str:
    """删除前导出该案件全量数据为 JSON，返回落盘路径。

    快照覆盖：案件主记录、主机、事件子树、各 host 维表、案件直辖表、
    incident_report_audit（随 incident_reports 级联删除，单独落盘）。
    """
    ph = _host_ph(host_ids)
    case_row = _resolve_case(conn, cid) or {}
    snapshot = {
        "case_id": cid,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "case": case_row,
        "hosts": [
            dict(r) for r in conn.execute(
                "SELECT * FROM hosts WHERE case_id=?", (cid,)).fetchall()
        ],
        "tables": {},
    }
    # host 维表 + 案件直辖表（跳过已在上面单独导出的 hosts/cases）
    for name, frm, params in _iter_ops(host_ids, cid):
        if name in ("hosts", "cases"):
            continue
        rows = conn.execute(f"SELECT * {frm}", params).fetchall()
        snapshot["tables"][name] = [dict(r) for r in rows]
    # incident_report_audit（随 incident_reports 级联，单独导出）
    rep_ids = [r["id"] for r in conn.execute(
        "SELECT id FROM incident_reports WHERE case_id=?", (cid,)).fetchall()]
    if rep_ids:
        rph = ",".join("?" for _ in rep_ids)
        snapshot["tables"]["incident_report_audit"] = [
            dict(r) for r in conn.execute(
                f"SELECT * FROM incident_report_audit WHERE report_id IN ({rph})",
                rep_ids).fetchall()]
    # 落盘
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    path = SNAPSHOT_DIR / f"{cid}_{ts}.json"
    path.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return str(path)


def _write_data_purge_log(conn, case: dict, operator: dict, counts: dict,
                          snapshot_path: Optional[str], client_ip: str) -> None:
    """在事务内写入 data_purge_log（清案操作留痕，永不清除）。"""
    total = sum(counts.values())
    conn.execute(
        """INSERT INTO data_purge_log
           (case_id, case_number, case_name, operator_id, operator_name,
            total_rows, table_counts, snapshot_path, client_ip, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'done')""",
        (case["id"], case["case_number"], case["name"],
         operator.get("id"), operator.get("username"),
         total, json.dumps(counts, ensure_ascii=False), snapshot_path, client_ip),
    )


def _write_audit_log(conn, operator: dict, case_id: int, case_number,
                     counts: dict, client_ip: str) -> None:
    """在事务内写入 audit_logs（action_type='case_purge'）。

    注意：此处直接复用 audit_logs 的写入 SQL，在同一连接的事务内提交，
    而非调用 audit_service.create_audit_log（其会另开一个连接，破坏 §3.9
    要求的单事务原子性，且会与 BEGIN IMMEDIATE 写锁冲突）。
    """
    total = sum(counts.values())
    detail = json.dumps({
        "case_id": case_id,
        "case_number": case_number,
        "total_rows": total,
        "table_counts": counts,
    }, ensure_ascii=False)
    conn.execute(
        """INSERT INTO audit_logs
           (user_id, username, action_type, detail, target_type, target_id, ip_address)
           VALUES (?, ?, 'case_purge', ?, 'case', ?, ?)""",
        (operator.get("id", 0), operator.get("username", "unknown"),
         detail, str(case_id), client_ip or ""),
    )


def preview_case_purge(case_id: int) -> dict:
    """预览清案影响面：返回各表预估删除行数（案件不存在 → 404）。"""
    with get_connection() as conn:
        case = _resolve_case(conn, case_id)
        if not case:
            raise HTTPException(status_code=404, detail="案件不存在或已清除")
        cid = case["id"]
        host_ids = [r["id"] for r in conn.execute(
            "SELECT id FROM hosts WHERE case_id=?", (cid,)).fetchall()]
        counts = _preview_ordered(conn, host_ids, cid)
        # 规则命中统计归零预估：rules 为全局配置表不删除，仅预估需归零的行数
        # （hit_count>0 的规则将在清案时被重置为 0）。
        rules_reset = conn.execute(
            "SELECT COUNT(*) FROM rules WHERE hit_count>0"
        ).fetchone()[0]
        counts["rules_reset"] = rules_reset
        return {
            "case_id": cid,
            "case_number": case["case_number"],
            "case_name": case["name"],
            "host_count": len(host_ids),
            "total_rows": sum(counts.values()),
            "table_counts": counts,
            "rules_reset": rules_reset,
        }


def purge_case(case_id: int, confirm_text: str, operator: dict,
               export_snapshot: bool = True, client_ip: str = "") -> dict:
    """清空指定案件及其全部级联数据（被遗忘权）。

    Args:
        case_id: 目标案件的数字主键 ID（精确匹配，禁模糊）。
        confirm_text: 二次确认文本，须等于 ``str(case_id)``。
        operator: 当前操作人字典（含 id / username / role）。
        export_snapshot: 删除前是否导出 JSON 快照（默认开启，决策点 5）。
        client_ip: 客户端 IP（写入审计留痕）。

    Returns:
        {purged_case_id, case_number, total_rows, table_counts, snapshot_path}

    Raises:
        HTTPException 404: 案件不存在或已清除（重复清同一案件天然幂等）。
        HTTPException 400: 确认文本与案件 ID 不一致。
        HTTPException 409: 该案件仍有 running/pending 的 AI 分析任务。
    """
    with get_connection() as conn:
        # 立即获取 SQLite 写锁，串行化并发清案
        conn.execute("BEGIN IMMEDIATE")

        case = _resolve_case(conn, case_id)
        if not case:
            raise HTTPException(status_code=404, detail="案件不存在或已清除")
        cid = case["id"]

        if confirm_text != str(cid):
            raise HTTPException(status_code=400, detail="确认文本与案件 ID 不一致")

        host_ids = [r["id"] for r in conn.execute(
            "SELECT id FROM hosts WHERE case_id=?", (cid,)).fetchall()]

        # 可选安全闸门：存在进行中的 AI 任务则拒绝（§3.9）
        pending = conn.execute(
            f"SELECT COUNT(*) FROM ai_tasks WHERE host_id IN ({_host_ph(host_ids)}) "
            f"AND status IN ('running', 'pending')", host_ids).fetchone()[0]
        if pending > 0:
            raise HTTPException(
                status_code=409,
                detail="该案件仍有正在进行中的 AI 分析任务，请完成后再清",
            )

        # 删前导出快照（默认开启；必须在 DELETE 之前读取全量数据）
        snapshot_path = _snapshot(conn, cid, host_ids) if export_snapshot else None

        # 按 §3.3 顺序逐表删除并累计行数
        counts = _delete_ordered(conn, host_ids, cid)

        # 归零规则引擎累计命中统计（rules 是全局配置表不能删，但 hit_count /
        # last_hit_at / avg_risk_score 是规则引擎分析时累加的运行时脏数据）。
        # 不归零会导致清案后态势感知大屏「规则命中」(dashboard.py 对
        # rules.hit_count 做 SUM 聚合) 仍显示历史累计命中数，无法归零。
        rules_reset = conn.execute(
            "UPDATE rules SET hit_count=0, last_hit_at=NULL, avg_risk_score=0"
        ).rowcount
        counts["rules_reset"] = rules_reset

        # 审计：同一事务内写入 data_purge_log + audit_logs（原子性）
        _write_data_purge_log(conn, case, operator, counts, snapshot_path, client_ip)
        _write_audit_log(conn, operator, cid, case["case_number"], counts, client_ip)

    # with 退出即 commit；异常则 rollback（get_connection 兜底）
    return {
        "purged_case_id": cid,
        "case_number": case["case_number"],
        "total_rows": sum(counts.values()),
        "table_counts": counts,
        "snapshot_path": snapshot_path,
    }
