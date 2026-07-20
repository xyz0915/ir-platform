"""QA 独立验证：系统参数页「清空某个案件」（被遗忘权 / 隐私合规）。

严格安全红线：所有测试一律使用临时 SQLite 文件，绝不指向 backend/data/ir_platform.db
（或任何 backend/data/*.db 真实业务库）。

覆盖 docs/case_purge_design.md §7 全部验收场景：
  主场景 8 条：①全表归零 ②重复清幂等404 ③非admin→403 ④确认文本不一致→400
             ⑤外键顺序(before security_events) ⑥中途异常→全回滚 ⑦审计各写1条永不清除
             ⑧默认快照生成(可取消)
  边界 5 条：A 不存在ID→404  B 非数值/模糊→422  C UI不破坏配置表且非admin不显卡片
            D 路由顺序不被/{case_id}吞  E 旧DELETE行为完全不变
  额外：跨案件精度(只清目标案件) + 409 进行中AI任务闸门

运行：cd backend && python -m pytest tests/test_purge_qa.py -v
"""

import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import app.config as config_module  # noqa: E402

# ── 安全红线：模块加载即把 DB_PATH 钉死在临时目录，杜绝任何误连真实库的可能 ──
_SAFETY_TMP = Path(tempfile.mkdtemp(prefix="qa_purge_safety_"))
settings = config_module.settings
settings.DB_PATH = str(_SAFETY_TMP / "module_load_never_used.db")

from app.database import get_connection, init_db  # noqa: E402
from app.services import purge_service  # noqa: E402
from fastapi import HTTPException  # noqa: E402

# 与 purge_service._iter_ops 的 host 表白名单对齐（用于造数与断言）
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
# 事件子树表（外键顺序敏感）
EVENT_TREE_TABLES = ["event_disposition_log", "status_history", "security_events"]
ADMIN = {"id": 1, "username": "admin", "role": "admin"}


# ── 造数辅助 ──────────────────────────────────────────────
def _seed_host_table(conn, table: str, host_id: int) -> None:
    """向 host 维表插入一行（按 host_id），自动补全 NOT NULL 列。"""
    cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
    row = {"host_id": host_id}
    for c in cols:
        name = c["name"]
        if name in row:
            continue
        if c["pk"]:
            ctype = (c["type"] or "").upper()
            if "INT" in ctype:
                continue
            row[name] = f"{table}-{host_id}-{name}"
            continue
        if c["notnull"]:
            ctype = (c["type"] or "").upper()
            if "INT" in ctype:
                row[name] = 0
            elif "REAL" in ctype or "FLOA" in ctype:
                row[name] = 0.0
            else:
                row[name] = f"{table}-{host_id}-{name}"
    cols_sql = ", ".join(row.keys())
    ph = ", ".join("?" for _ in row)
    conn.execute(
        f"INSERT INTO {table} ({cols_sql}) VALUES ({ph})", list(row.values())
    )


def _seed_case(conn, case_id: int, host_ids=(1, 2), ai_status: str = "completed") -> None:
    """灌入一个含主机/事件/各表造数据的案件（host_ids 可指定以构造多案件）。"""
    conn.execute(
        "INSERT INTO cases (id, name, case_number, status) VALUES (?, ?, ?, ?)",
        (case_id, f"案件{case_id}", f"CASE-000{case_id}", "open"),
    )
    for hid in host_ids:
        conn.execute(
            "INSERT INTO hosts (id, case_id, hostname, ip_address) VALUES (?, ?, ?, ?)",
            (hid, case_id, f"host-{hid}", f"10.0.0.{hid}"),
        )
    # 事件子树（event_id 用事件主键，确保 event_disposition_log 引用存在；按 case_id 区分避免多案件重复主键）
    conn.execute(
        "INSERT INTO security_events (id, timestamp, host_id, event_type, severity, event_key) "
        "VALUES ('evt-c%d-1', '2026-01-01T00:00:00Z', ?, 'malware', 'high', 'k1')" % case_id,
        (host_ids[0],),
    )
    conn.execute(
        "INSERT INTO security_events (id, timestamp, host_id, event_type, severity, event_key) "
        "VALUES ('evt-c%d-2', '2026-01-01T00:00:01Z', ?, 'phishing', 'medium', 'k2')" % case_id,
        (host_ids[1],),
    )
    conn.execute(
        "INSERT INTO event_disposition_log (event_id, action, operator) "
        "VALUES ('evt-c%d-1', 'block', 'admin')" % case_id
    )
    conn.execute(
        "INSERT INTO status_history (event_id, new_status, operator) "
        "VALUES ('evt-c%d-1', 'resolved', 'admin')" % case_id
    )
    # host 维表
    for t in HOST_TABLES:
        for hid in host_ids:
            _seed_host_table(conn, t, hid)
    # 案件直辖表
    conn.execute(
        "INSERT INTO alerts (host_id, case_id, rule_name, title) VALUES (?, ?, 'r', 't')",
        (host_ids[0], case_id),
    )
    conn.execute(
        "INSERT INTO agent_imports (host_id, case_id, collector_type, raw_json) "
        "VALUES (?, ?, 'manual', '{}')", (host_ids[0], case_id)
    )
    conn.execute(
        "INSERT INTO remediation_checklist (host_id, case_id, items) VALUES (?, ?, '{}')",
        (host_ids[0], case_id),
    )
    conn.execute(
        "INSERT INTO ai_analysis_reports (host_id, case_id, risk_assessment) VALUES (?, ?, 'low')",
        (host_ids[0], case_id),
    )
    conn.execute("INSERT INTO incident_reports (case_id, title) VALUES (?, 'IR')", (case_id,))
    rid = conn.execute(
        "SELECT id FROM incident_reports WHERE case_id=?", (case_id,)
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO incident_report_audit (report_id, action) VALUES (?, 'created')", (rid,)
    )
    # 把 ai_tasks 设为指定状态（默认 completed，避免触发 409 闸门）
    ph = ",".join("?" for _ in host_ids)
    conn.execute(
        f"UPDATE ai_tasks SET status=? WHERE host_id IN ({ph})", (ai_status, *host_ids)
    )


def _setup_temp_db(tmp_path: Path, name: str = "qa_isolated") -> Path:
    """把 DB 指向临时文件并初始化 schema（不影响真实库）。"""
    db_path = tmp_path / f"{name}.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    settings.DB_PATH = str(db_path)
    init_db()
    return db_path


def _cleanup_snapshots(case_ids):
    """清理清案测试产生的快照文件（落盘在 backend/app/data/purge_snapshots）。"""
    snap_dir = purge_service.SNAPSHOT_DIR
    if not snap_dir.exists():
        return
    for cid in case_ids:
        for f in snap_dir.glob(f"{cid}_*.json"):
            f.unlink(missing_ok=True)


@pytest.fixture(autouse=True)
def _temp_snapshot_dir(tmp_path):
    """把快照落盘目录重定向到临时目录，避免污染真实项目目录（backend/app/data/）
    并避免清理时触发批量删除安全拦截。每个测试使用独立临时快照目录。"""
    original = purge_service.SNAPSHOT_DIR
    purge_service.SNAPSHOT_DIR = tmp_path / "purge_snapshots"
    yield
    purge_service.SNAPSHOT_DIR = original


# ── ① 正常清案：约 30 张表归零 + 跨案件精度 ──────────────
def test_qa_clear_all_tables_and_cross_case_precision(tmp_path):
    """① 清 case1 后，case1 相关行全部归零；case2 数据原样保留（只清目标案件）。"""
    _setup_temp_db(tmp_path)
    with get_connection() as conn:
        _seed_case(conn, 1, host_ids=(1, 2))
        _seed_case(conn, 2, host_ids=(3, 4))  # 第二个案件作为"不该被清"的对照

    res = purge_service.purge_case(1, "1", ADMIN, export_snapshot=True)
    assert res["purged_case_id"] == 1
    assert res["total_rows"] > 0

    with get_connection() as conn:
        # 目标案件 case1 全部归零
        assert conn.execute("SELECT COUNT(*) FROM cases WHERE id=1").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM hosts WHERE case_id=1").fetchone()[0] == 0
        # 事件子树：event_disposition_log / status_history 为全局表（按 event_id 关联，无 host_id/case_id 列）。
        # 清 case1 后应仅残留 case2 的 1 行（全局 2→1 证明 case1 的相关行已被清，且跨案件精度保持）
        assert conn.execute("SELECT COUNT(*) FROM event_disposition_log").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM status_history").fetchone()[0] == 1
        # security_events 按 host_id 计数（case2 的 host 3,4 不在范围内）
        for t in ["security_events"] + HOST_TABLES:
            n = conn.execute(f"SELECT COUNT(*) FROM {t} WHERE host_id IN (1, 2)").fetchone()[0]
            assert n == 0, f"{t} 残留 host 行: {n}"
        for t in CASE_DIRECT_TABLES:
            n = conn.execute(f"SELECT COUNT(*) FROM {t} WHERE case_id=1").fetchone()[0]
            assert n == 0, f"{t} 残留 case 行: {n}"

        # 审计表写入且全局表不受影响
        assert conn.execute("SELECT COUNT(*) FROM data_purge_log").fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM audit_logs WHERE action_type='case_purge'"
        ).fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] >= 1
        assert conn.execute("SELECT COUNT(*) FROM system_settings").fetchone()[0] >= 1
        assert conn.execute("SELECT COUNT(*) FROM rules").fetchone()[0] >= 1

        # 跨案件精度：case2 数据必须原样保留
        assert conn.execute("SELECT COUNT(*) FROM cases WHERE id=2").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM hosts WHERE case_id=2").fetchone()[0] == 2
        assert conn.execute(
            "SELECT COUNT(*) FROM security_events WHERE host_id IN (3, 4)"
        ).fetchone()[0] == 2
        for t in HOST_TABLES:
            n = conn.execute(f"SELECT COUNT(*) FROM {t} WHERE host_id IN (3, 4)").fetchone()[0]
            assert n >= 1, f"case2 的 {t} 被误清: {n}"

    # 快照文件生成且内容完整
    assert os.path.exists(res["snapshot_path"])
    snap = json.loads(Path(res["snapshot_path"]).read_text(encoding="utf-8"))
    assert snap["case_id"] == 1 and snap["case"]["name"] == "案件1"
    assert "security_events" in snap["tables"]
    assert "incident_report_audit" in snap["tables"]
    _cleanup_snapshots([1])


# ── ② 重复清同一案件 → 404 幂等 ──────────────────────────
def test_qa_idempotent_404(tmp_path):
    """② 重复清同一案件，第二次返回 404，审计表仅 1 条。"""
    _setup_temp_db(tmp_path)
    with get_connection() as conn:
        _seed_case(conn, 1)
    purge_service.purge_case(1, "1", ADMIN)
    try:
        purge_service.purge_case(1, "1", ADMIN)
        assert False, "重复清案应抛出 404"
    except HTTPException as e:
        assert e.status_code == 404
    with get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM data_purge_log").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM cases WHERE id=1").fetchone()[0] == 0


# ── ③ 非 admin 调用 → 403（API 级）──────────────────────
@pytest.fixture
def api_client(tmp_path):
    """隔离的 FastAPI TestClient：临时库 + 依赖注入模拟登录角色。"""
    db_path = tmp_path / "qa_api.db"
    settings.DB_PATH = str(db_path)
    # 安全断言：DB 必须落在临时目录，绝不可能是真实 backend/data 下
    assert str(db_path).startswith(tempfile.gettempdir())
    from app.main import app
    from app.services.auth_service import get_current_user
    from fastapi.testclient import TestClient

    app.dependency_overrides.clear()

    def _role(role):
        # 使用已存在的默认管理员 id=1，避免 audit_logs.user_id 外键约束失败
        def _user():
            return {"id": 1, "username": f"u-{role}", "role": role}
        return _user

    app.dependency_overrides[get_current_user] = _role("admin")
    with TestClient(app) as client:
        yield client, app, _role
    app.dependency_overrides.clear()


def _seed_via_conn(case_id=1, host_ids=(1, 2), ai_status="completed"):
    with get_connection() as conn:
        _seed_case(conn, case_id, host_ids, ai_status)


def test_qa_non_admin_forbidden(api_client):
    """③ 非 admin 调 preview 与 purge 均返回 403，且数据不被删。"""
    client, app, role_fn = api_client
    _seed_via_conn(1)

    # 切到非 admin
    from app.services.auth_service import get_current_user
    app.dependency_overrides[get_current_user] = role_fn("analyst")

    r_prev = client.get("/api/cases/purge-preview/1")
    assert r_prev.status_code == 403, r_prev.text
    r_purge = client.post(
        "/api/cases/purge",
        json={"case_id": 1, "confirm_text": "1", "export_snapshot": True},
    )
    assert r_purge.status_code == 403, r_purge.text

    # 数据未被删除
    with get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM cases WHERE id=1").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM data_purge_log").fetchone()[0] == 0
    # 恢复 admin（fixture teardown 会清 override，这里仅保险）
    app.dependency_overrides[get_current_user] = role_fn("admin")


# ── ④ 确认文本不一致 → 400 ───────────────────────────────
def test_qa_confirm_mismatch_400(tmp_path):
    """④ 选案件 A(id=1) 但 confirm_text='2' → 400，数据不变。"""
    _setup_temp_db(tmp_path)
    with get_connection() as conn:
        _seed_case(conn, 1)
    try:
        purge_service.purge_case(1, "2", ADMIN)
        assert False, "确认文本不一致应抛出 400"
    except HTTPException as e:
        assert e.status_code == 400
    with get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM cases WHERE id=1").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM security_events").fetchone()[0] == 2


# ── ⑤ 外键顺序：event_disposition_log 先于 security_events ──
def test_qa_fk_order_event_disposition_before_security_events(tmp_path):
    """⑤ 含 event_disposition_log+security_events 的案件可正常清（不报外键冲突）；
    反向顺序（先删 security_events）必报 FK 冲突，反证顺序正确。"""
    _setup_temp_db(tmp_path)
    with get_connection() as conn:
        _seed_case(conn, 1)

    # 正确顺序：成功，两张表均清零
    res = purge_service.purge_case(1, "1", ADMIN, export_snapshot=False)
    assert res["table_counts"]["event_disposition_log"] >= 1
    assert res["table_counts"]["security_events"] == 2
    with get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM event_disposition_log").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM security_events").fetchone()[0] == 0
    _cleanup_snapshots([1])

    # 反向顺序反证：先删 security_events 必触发外键冲突
    _setup_temp_db(tmp_path)
    with get_connection() as conn:
        _seed_case(conn, 1)
    original = purge_service._delete_ordered

    def _wrong_order(conn, host_ids, cid):
        # 故意先删父表 security_events，再删子表 event_disposition_log
        purge_service._del(
            conn, f"DELETE FROM security_events WHERE host_id IN ({','.join('?' for _ in host_ids)})",
            host_ids,
        )
        purge_service._del(
            conn,
            f"DELETE FROM event_disposition_log WHERE event_id IN "
            f"(SELECT id FROM security_events WHERE host_id IN ({','.join('?' for _ in host_ids)}))",
            host_ids,
        )
        raise RuntimeError("injected-after-fk-check")  # 仅用于提前终止，便于断言FK错误已发生

    purge_service._delete_ordered = _wrong_order
    try:
        try:
            purge_service.purge_case(1, "1", ADMIN, export_snapshot=False)
            assert False, "反向顺序应触发外键冲突"
        except sqlite3.IntegrityError:
            pass  # 期望：FOREIGN KEY constraint failed
        except RuntimeError:
            assert False, "未触发外键冲突（顺序错误未被验证）"
    finally:
        purge_service._delete_ordered = original
        _cleanup_snapshots([1])


# ── ⑥ 中途异常 → 整事务回滚，数据原样保留 ────────────────
def test_qa_rollback_on_midway_error(tmp_path):
    """⑥ 删除中途异常 → 整事务回滚，案件与原数据原样保留，审计无记录。"""
    _setup_temp_db(tmp_path)
    with get_connection() as conn:
        _seed_case(conn, 1)

    original = purge_service._delete_ordered

    def _boom(conn, host_ids, cid):
        # 模拟删到一半：先删 hosts，再抛异常（此时 BEGIN IMMEDIATE 事务已开启）
        purge_service._del(conn, "DELETE FROM hosts WHERE case_id=?", (cid,))
        raise RuntimeError("模拟中途失败")

    purge_service._delete_ordered = _boom
    try:
        try:
            purge_service.purge_case(1, "1", ADMIN)
        except RuntimeError:
            pass
        with get_connection() as conn:
            # 全表原样保留（事务回滚）
            assert conn.execute("SELECT COUNT(*) FROM cases WHERE id=1").fetchone()[0] == 1
            assert conn.execute("SELECT COUNT(*) FROM hosts WHERE case_id=1").fetchone()[0] == 2
            assert conn.execute(
                "SELECT COUNT(*) FROM security_events WHERE host_id IN (1, 2)"
            ).fetchone()[0] == 2
            for t in CASE_DIRECT_TABLES:
                assert conn.execute(f"SELECT COUNT(*) FROM {t} WHERE case_id=1").fetchone()[0] >= 1, t
            # 无审计记录（事务回滚，快照是删前导出，应清理）
            assert conn.execute("SELECT COUNT(*) FROM data_purge_log").fetchone()[0] == 0
    finally:
        purge_service._delete_ordered = original
        _cleanup_snapshots([1])


# ── ⑦ 审计表各写 1 条且永不被清 ─────────────────────────
def test_qa_audit_logs_written_and_never_purged(tmp_path):
    """⑦ 每次清案各写 1 条 data_purge_log + audit_logs；多次清案日志累加（永不清除）。"""
    _setup_temp_db(tmp_path)
    with get_connection() as conn:
        _seed_case(conn, 1)
        _seed_case(conn, 2, host_ids=(3, 4))

    purge_service.purge_case(1, "1", ADMIN, export_snapshot=False)
    purge_service.purge_case(2, "2", ADMIN, export_snapshot=False)

    with get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM data_purge_log").fetchone()[0] == 2
        assert conn.execute(
            "SELECT COUNT(*) FROM audit_logs WHERE action_type='case_purge'"
        ).fetchone()[0] == 2

        # 校验 data_purge_log 字段齐全
        rows = conn.execute(
            "SELECT case_id, case_number, operator_name, total_rows, table_counts, "
            "snapshot_path, status FROM data_purge_log ORDER BY case_id"
        ).fetchall()
        for r in rows:
            r = dict(r)
            assert r["case_number"].startswith("CASE-000")
            assert r["operator_name"] == "admin"
            assert r["status"] == "done"
            assert r["snapshot_path"] is None  # export_snapshot=False
            tc = json.loads(r["table_counts"])
            assert isinstance(tc, dict) and "security_events" in tc

        # 校验 audit_logs 内容含案件ID/编号/行数
        a = dict(conn.execute(
            "SELECT detail FROM audit_logs WHERE action_type='case_purge' LIMIT 1"
        ).fetchone())
        detail = json.loads(a["detail"])
        assert "case_id" in detail and "case_number" in detail and "total_rows" in detail
    _cleanup_snapshots([1, 2])


# ── ⑧ 默认开快照；取消勾选则 null ───────────────────────
def test_qa_snapshot_default_on_and_off(tmp_path):
    """⑧ 默认 export_snapshot=True 生成快照并回写路径；False 不生成且路径为 null。"""
    _setup_temp_db(tmp_path)
    with get_connection() as conn:
        _seed_case(conn, 1)

    # 默认开启
    res_on = purge_service.purge_case(1, "1", ADMIN, export_snapshot=True)
    assert res_on["snapshot_path"] is not None
    assert os.path.exists(res_on["snapshot_path"])
    with get_connection() as conn:
        log = dict(conn.execute("SELECT snapshot_path FROM data_purge_log").fetchone())
        assert log["snapshot_path"] == res_on["snapshot_path"]
    _cleanup_snapshots([1])

    # 取消勾选（使用独立库，避免与"on"部分的数据残留互相干扰）
    _setup_temp_db(tmp_path, "off")
    with get_connection() as conn:
        _seed_case(conn, 1)
    res_off = purge_service.purge_case(1, "1", ADMIN, export_snapshot=False)
    assert res_off["snapshot_path"] is None
    with get_connection() as conn:
        log = dict(conn.execute("SELECT snapshot_path FROM data_purge_log").fetchone())
        assert log["snapshot_path"] is None
    # 不应生成任何快照文件
    snap_dir = purge_service.SNAPSHOT_DIR
    if snap_dir.exists():
        assert not list(snap_dir.glob("1_*.json"))


# ── 边界 A：不存在的 ID → 404 ────────────────────────────
def test_qa_nonexistent_404(tmp_path):
    """边界A：不存在的 case_id → 404。"""
    _setup_temp_db(tmp_path)
    try:
        purge_service.purge_case(999, "999", ADMIN)
        assert False, "不存在的案件应抛出 404"
    except HTTPException as e:
        assert e.status_code == 404


# ── 边界 B：非数值/模糊 ID → 422，不误清 ────────────────
def test_qa_non_numeric_422(api_client):
    """边界B：case_id 非整数 → API 层 422 校验，绝不进入清案逻辑。"""
    client, app, _ = api_client
    _seed_via_conn(1)
    # 非数值 case_id
    r = client.post(
        "/api/cases/purge",
        json={"case_id": "abc", "confirm_text": "abc", "export_snapshot": True},
    )
    assert r.status_code == 422, r.text
    # 模糊/编号匹配（非数值主键）同样 422
    r2 = client.post(
        "/api/cases/purge",
        json={"case_id": "CASE-0001", "confirm_text": "CASE-0001", "export_snapshot": True},
    )
    assert r2.status_code == 422, r2.text
    # 数据未被误清
    with get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM cases WHERE id=1").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM data_purge_log").fetchone()[0] == 0
    _cleanup_snapshots([1])


# ── 边界 D：路由顺序不被 /{case_id} 吞 ───────────────────
def test_qa_route_order_not_swallowed(api_client):
    """边界D：/purge-preview/{id} 与 /purge 不被 /{case_id} 拦截；旧 list/get 正常。"""
    client, app, _ = api_client
    _seed_via_conn(5)

    # 预览路由（GET）必须命中 purge-preview，而非被 GET /{case_id} 按 422 吞掉
    r_prev = client.get("/api/cases/purge-preview/5")
    assert r_prev.status_code == 200, r_prev.text
    assert r_prev.json()["data"]["case_id"] == 5

    # 执行路由（POST /purge）必须 200，而非被 POST /{case_id}（不存在）或 422 吞掉
    r_purge = client.post(
        "/api/cases/purge",
        json={"case_id": 5, "confirm_text": "5", "export_snapshot": False},
    )
    assert r_purge.status_code == 200, r_purge.text
    assert r_purge.json()["code"] == 0

    # 旧接口回归：GET /{case_id} 仍正常返回案件（清前）
    _seed_via_conn(7)
    r_get = client.get("/api/cases/7")
    assert r_get.status_code == 200, r_get.text
    assert r_get.json()["data"]["id"] == 7

    # 非数值预览 → 422（证明参数校验生效，而非被吞成别的）
    r_bad = client.get("/api/cases/purge-preview/abc")
    assert r_bad.status_code == 422, r_bad.text
    _cleanup_snapshots([5])


# ── 边界 E：旧 DELETE /api/cases/{id} 行为完全不变 ───────
def test_qa_old_delete_unchanged(api_client):
    """边界E：旧 DELETE /api/cases/{id} 仍可删、返回成功、案件消失；
    且未新增 admin 校验（非 admin 也能删，权限模型不变）。"""
    client, app, role_fn = api_client
    from app.services.auth_service import get_current_user

    # admin 创建并删除
    created = client.post(
        "/api/cases",
        json={"name": "旧接口案件", "case_number": "OLD-1", "description": "x", "priority": "medium"},
    )
    assert created.status_code == 200, created.text
    cid = created.json()["data"]["id"]
    deleted = client.delete(f"/api/cases/{cid}")
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["code"] == 0
    assert client.get(f"/api/cases/{cid}").status_code == 404

    # 权限模型不变：非 admin 仍可直接删除（确认 delete_case 未加 admin 校验）
    app.dependency_overrides[get_current_user] = role_fn("analyst")
    created2 = client.post(
        "/api/cases",
        json={"name": "非admin删", "case_number": "OLD-2", "description": "x", "priority": "medium"},
    )
    assert created2.status_code == 200, created2.text
    cid2 = created2.json()["data"]["id"]
    deleted2 = client.delete(f"/api/cases/{cid2}")
    assert deleted2.status_code == 200, deleted2.text
    app.dependency_overrides[get_current_user] = role_fn("admin")


# ── 边界 C：前端不破坏配置表 + 非 admin 不显卡片（静态契约校验）──
def test_qa_frontend_purge_card_contract():
    """边界C：SystemParamsView.vue 配置表逻辑未被破坏，清案卡片受 isAdmin 控制。"""
    vue_path = Path(
        r"c:/Users/xyz/WorkBuddy/2026-07-06-17-00-58/frontend/src/views/settings/SystemParamsView.vue"
    )
    text = vue_path.read_text(encoding="utf-8")

    # 原有配置表未被破坏
    assert 'el-table :data="paramList"' in text, "系统参数配置表 el-table 被破坏"
    assert "getSystemSettings" in text, "原有获取系统参数逻辑被移除"

    # 清案卡片存在且按钮受 isAdmin 控制（仅 admin 可见）
    assert "清空此案件（不可撤销）" in text
    # 危险按钮必须带 v-if="isAdmin" 保护（非 admin 不显示卡片按钮）
    idx = text.index("清空此案件（不可撤销）")
    pre = text[max(0, idx - 400):idx]  # 按钮标签前 400 字符内应含 isAdmin 守卫
    assert 'v-if="isAdmin"' in pre, "清案按钮未按 isAdmin 显隐"

    # 接口调用齐全
    assert "casesApi.getCasesWithHosts()" in text
    assert "casesApi.purgePreview(" in text
    assert "casesApi.purge(" in text

    # 导出快照默认勾选（决策点 5：默认开启）
    assert "exportSnapshot = ref(true)" in text, "导出快照未默认开启"


# ── 额外：进行中 AI 任务安全闸门 → 409 ───────────────────
def test_qa_running_ai_task_safety_gate_409(tmp_path):
    """进行中(running)的 AI 任务存在时，purge 返回 409 且数据不被删。"""
    _setup_temp_db(tmp_path)
    with get_connection() as conn:
        _seed_case(conn, 1, ai_status="running")
    try:
        purge_service.purge_case(1, "1", ADMIN, export_snapshot=False)
        assert False, "存在进行中 AI 任务应抛出 409"
    except HTTPException as e:
        assert e.status_code == 409
    with get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM cases WHERE id=1").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM data_purge_log").fetchone()[0] == 0
    _cleanup_snapshots([1])


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
