"""隔离环境下的清案服务自测（绝不触碰真实业务库）。

所有测试均将 ``app.config.settings.DB_PATH`` 指向临时 SQLite 文件，
通过 ``init_db()`` 建表并灌入造数据，验证 ``purge_case`` 的事务原子性、
级联清除、审计写入、快照生成与幂等 404。

运行方式（任选其一，均不会指向 backend/data/ 下的真实库）：
    cd backend && python -m pytest tests/test_purge_isolated.py -v
    cd backend && python tests/test_purge_isolated.py
"""

import inspect
import json
import os
import sys
import tempfile
import traceback
from pathlib import Path

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import app.config as config_module  # noqa: E402
settings = config_module.settings  # noqa: E402
from app.database import get_connection, init_db  # noqa: E402
from app.services import purge_service  # noqa: E402
from fastapi import HTTPException  # noqa: E402


# ── 造数据用的 host 维表集合（与 purge_service._iter_ops 的 host 白名单对齐）──
HOST_TABLES = [
    "ai_audit_log", "ai_tasks", "agent_baselines", "ai_evidence_refills",
    "import_records", "host_profiles", "analysis_results", "abnormal_processes",
    "suspicious_connections", "suspicious_startup_items", "persistence_items",
    "timeline_events", "ioc_hits", "network_connections", "file_hashes",
    "wmi_subscriptions", "registry_keys", "process_events", "webshells",
    "memory_shells", "agents", "normalized_logs",
]
CASE_DIRECT_TABLES = [
    "alerts", "agent_imports", "remediation_checklist",
    "ai_analysis_reports", "incident_reports",
]


def _setup_temp_db(tmp_path: Path) -> Path:
    """把 DB 指向临时文件并初始化 schema（不影响真实库）。"""
    db_path = tmp_path / "test_ir_isolated.db"
    settings.DB_PATH = str(db_path)
    init_db()
    return db_path


def _seed_host_table(conn, table: str, host_id: int) -> None:
    """向 host 维表插入一行（按 host_id），自动补全 NOT NULL 列。

    通过 PRAGMA table_info 读取列定义：NOT NULL 且非主键的列按类型
    填充占位值（INTEGER→0、REAL→0.0、文本→唯一串），避免逐一
    列举各表约束。security_events 等 TEXT 主键表由调用方显式处理。
    """
    cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
    row = {"host_id": host_id}
    for c in cols:
        name = c["name"]
        if name in row:
            continue
        if c["pk"]:
            ctype = (c["type"] or "").upper()
            if "INT" in ctype:
                # 自增整数主键：留空，交由 AUTOINCREMENT
                continue
            # TEXT 主键（如 security_events）：本测试由调用方显式处理，兜底给唯一串
            row[name] = f"{table}-{host_id}-{name}"
            continue
        if c["notnull"]:
            ctype = (c["type"] or "").upper()
            if "INT" in ctype:
                row[name] = 0
            elif "REAL" in ctype or "FLOA" in ctype:
                row[name] = 0.0
            else:
                # 文本类型（含 UNIQUE 列）：用唯一串避免冲突
                row[name] = f"{table}-{host_id}-{name}"
    cols_sql = ", ".join(row.keys())
    ph = ", ".join("?" for _ in row)
    try:
        conn.execute(
            f"INSERT INTO {table} ({cols_sql}) VALUES ({ph})", list(row.values())
        )
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"seed {table} failed: {exc} | row={row}") from exc


def _seed_case(conn, case_id: int = 1) -> None:
    """灌入一个含主机/事件/各表造数据的案件。"""
    conn.execute(
        "INSERT INTO cases (id, name, case_number, status) VALUES (?, ?, ?, ?)",
        (case_id, f"案件{case_id}", f"CASE-000{case_id}", "open"),
    )
    for hid in (1, 2):
        conn.execute(
            "INSERT INTO hosts (id, case_id, hostname, ip_address) VALUES (?, ?, ?, ?)",
            (hid, case_id, f"host-{hid}", f"10.0.0.{hid}"),
        )
    # 事件子树
    conn.execute(
        "INSERT INTO security_events (id, timestamp, host_id, event_type, severity, event_key) "
        "VALUES ('evt-1', '2026-01-01T00:00:00Z', 1, 'malware', 'high', 'k1')"
    )
    conn.execute(
        "INSERT INTO security_events (id, timestamp, host_id, event_type, severity, event_key) "
        "VALUES ('evt-2', '2026-01-01T00:00:01Z', 2, 'phishing', 'medium', 'k2')"
    )
    conn.execute(
        "INSERT INTO event_disposition_log (event_id, action, operator) VALUES ('evt-1', 'block', 'admin')"
    )
    conn.execute(
        "INSERT INTO status_history (event_id, new_status, operator) VALUES ('evt-1', 'resolved', 'admin')"
    )
    # host 维表（逐一按 host 1/2 插入，自动补全 NOT NULL 列）
    for t in HOST_TABLES:
        for hid in (1, 2):
            _seed_host_table(conn, t, hid)
    # ai_tasks 设为 completed，避免 409 安全闸门
    conn.execute("UPDATE ai_tasks SET status='completed' WHERE host_id IN (1, 2)")
    # 案件直辖表
    conn.execute("INSERT INTO alerts (host_id, case_id, rule_name, title) VALUES (1, ?, 'r', 't')", (case_id,))
    conn.execute(
        "INSERT INTO agent_imports (host_id, case_id, collector_type, raw_json) VALUES (1, ?, 'manual', '{}')",
        (case_id,),
    )
    conn.execute("INSERT INTO remediation_checklist (host_id, case_id, items) VALUES (1, ?, '{}')", (case_id,))
    conn.execute("INSERT INTO ai_analysis_reports (host_id, case_id, risk_assessment) VALUES (1, ?, 'low')", (case_id,))
    conn.execute("INSERT INTO incident_reports (case_id, title) VALUES (?, 'IR')", (case_id,))
    rid = conn.execute("SELECT id FROM incident_reports WHERE case_id=?", (case_id,)).fetchone()[0]
    conn.execute("INSERT INTO incident_report_audit (report_id, action) VALUES (?, 'created')", (rid,))


# ── 测试用例 ──────────────────────────────────────────────

def test_purge_clears_all_tables(tmp_path):
    """场景 1：正常清案，约 30 张表该案件相关行全部归零。"""
    _setup_temp_db(tmp_path)
    with get_connection() as conn:
        _seed_case(conn, 1)

    res = purge_service.purge_case(
        1, "1", {"id": 1, "username": "admin", "role": "admin"}, export_snapshot=True
    )
    assert res["purged_case_id"] == 1

    with get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM cases WHERE id=1").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM hosts WHERE case_id=1").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM security_events WHERE host_id IN (1, 2)").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM event_disposition_log").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM status_history").fetchone()[0] == 0
        for t in HOST_TABLES:
            assert conn.execute(f"SELECT COUNT(*) FROM {t} WHERE host_id IN (1, 2)").fetchone()[0] == 0, t
        for t in CASE_DIRECT_TABLES:
            assert conn.execute(f"SELECT COUNT(*) FROM {t} WHERE case_id=1").fetchone()[0] == 0, t
        # 审计表写入
        assert conn.execute("SELECT COUNT(*) FROM data_purge_log").fetchone()[0] == 1
        log = dict(conn.execute("SELECT * FROM data_purge_log").fetchone())
        assert log["case_id"] == 1 and log["status"] == "done" and log["snapshot_path"]
        assert conn.execute("SELECT COUNT(*) FROM audit_logs WHERE action_type='case_purge'").fetchone()[0] == 1
        # 全局表不受影响（永不被清）
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] >= 1
        assert conn.execute("SELECT COUNT(*) FROM system_settings").fetchone()[0] >= 1
        assert conn.execute("SELECT COUNT(*) FROM rules").fetchone()[0] >= 1

    # 快照文件生成且内容完整
    assert os.path.exists(res["snapshot_path"])
    snap = json.loads(Path(res["snapshot_path"]).read_text(encoding="utf-8"))
    assert snap["case_id"] == 1 and snap["case"]["name"] == "案件1"
    assert "security_events" in snap["tables"]
    os.remove(res["snapshot_path"])


def test_purge_idempotent_404(tmp_path):
    """场景 2：重复清同一案件，第二次返回 404，审计表仅 1 条。"""
    _setup_temp_db(tmp_path)
    with get_connection() as conn:
        _seed_case(conn, 1)
    purge_service.purge_case(1, "1", {"id": 1, "username": "admin", "role": "admin"})
    try:
        purge_service.purge_case(1, "1", {"id": 1, "username": "admin", "role": "admin"})
        assert False, "重复清案应抛出 404"
    except HTTPException as e:
        assert e.status_code == 404
    with get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM data_purge_log").fetchone()[0] == 1


def test_purge_confirm_mismatch_400(tmp_path):
    """场景 4：确认文本与案件 ID 不一致 → 400，数据不变。"""
    _setup_temp_db(tmp_path)
    with get_connection() as conn:
        _seed_case(conn, 1)
    try:
        purge_service.purge_case(1, "2", {"id": 1, "username": "admin", "role": "admin"})
        assert False, "确认文本不一致应抛出 400"
    except HTTPException as e:
        assert e.status_code == 400
    with get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM cases WHERE id=1").fetchone()[0] == 1


def test_purge_nonexistent_404(tmp_path):
    """边界 A：不存在的 ID → 404。"""
    _setup_temp_db(tmp_path)
    try:
        purge_service.purge_case(999, "999", {"id": 1, "username": "admin", "role": "admin"})
        assert False, "不存在的案件应抛出 404"
    except HTTPException as e:
        assert e.status_code == 404


def test_preview_counts(tmp_path):
    """预览接口：返回各表预估行数。"""
    _setup_temp_db(tmp_path)
    with get_connection() as conn:
        _seed_case(conn, 1)
    data = purge_service.preview_case_purge(1)
    assert data["case_id"] == 1
    assert data["table_counts"]["security_events"] == 2
    assert data["table_counts"]["hosts"] == 2
    assert data["total_rows"] > 0


def test_snapshot_disabled(tmp_path):
    """场景 8 补充：export_snapshot=false 时不生成快照。"""
    _setup_temp_db(tmp_path)
    with get_connection() as conn:
        _seed_case(conn, 1)
    res = purge_service.purge_case(
        1, "1", {"id": 1, "username": "admin", "role": "admin"}, export_snapshot=False
    )
    assert res["snapshot_path"] is None
    with get_connection() as conn:
        log = dict(conn.execute("SELECT * FROM data_purge_log").fetchone())
        assert log["snapshot_path"] is None


def test_rollback_on_error(tmp_path):
    """场景 6：删除中途异常 → 整事务回滚，案件与原数据原样保留。"""
    _setup_temp_db(tmp_path)
    with get_connection() as conn:
        _seed_case(conn, 1)

    original = purge_service._delete_ordered

    def _boom(conn, host_ids, cid):
        purge_service._del(conn, "DELETE FROM hosts WHERE case_id=?", (cid,))
        raise RuntimeError("模拟中途失败")

    purge_service._delete_ordered = _boom
    try:
        try:
            purge_service.purge_case(1, "1", {"id": 1, "username": "admin", "role": "admin"})
        except RuntimeError:
            pass
        with get_connection() as conn:
            assert conn.execute("SELECT COUNT(*) FROM cases WHERE id=1").fetchone()[0] == 1
            assert conn.execute("SELECT COUNT(*) FROM hosts WHERE case_id=1").fetchone()[0] == 2
            assert conn.execute("SELECT COUNT(*) FROM security_events WHERE host_id IN (1, 2)").fetchone()[0] == 2
            assert conn.execute("SELECT COUNT(*) FROM data_purge_log").fetchone()[0] == 0
    finally:
        purge_service._delete_ordered = original
        # 回滚前已生成快照（删前导出），此处清理测试产物
        snap_dir = purge_service.SNAPSHOT_DIR
        if snap_dir.exists():
            for f in snap_dir.glob("1_*.json"):
                f.unlink(missing_ok=True)


if __name__ == "__main__":
    funcs = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and inspect.isfunction(v)]
    passed = 0
    for fn in funcs:
        with tempfile.TemporaryDirectory() as td:
            try:
                fn(Path(td))
                print(f"PASS  {fn.__name__}")
                passed += 1
            except Exception as e:  # noqa: BLE001
                print(f"FAIL  {fn.__name__}: {e}")
                traceback.print_exc()
    print(f"\n{passed}/{len(funcs)} passed")
