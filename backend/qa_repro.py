import sys, tempfile, json
from pathlib import Path
BACKEND_DIR = Path(r"c:\Users\xyz\WorkBuddy\2026-07-06-17-00-58\backend")
sys.path.insert(0, str(BACKEND_DIR))
import app.config as config_module
settings = config_module.settings
settings.DB_PATH = str(Path(tempfile.mkdtemp()) / "repro.db")
from app.database import get_connection, init_db
from app.services import purge_service
from tests.test_purge_qa import _seed_case, HOST_TABLES, CASE_DIRECT_TABLES, ADMIN, _cleanup_snapshots

init_db()
with get_connection() as conn:
    _seed_case(conn, 1, host_ids=(1, 2))
    _seed_case(conn, 2, host_ids=(3, 4))

res = purge_service.purge_case(1, "1", ADMIN, export_snapshot=True)
print("purge res keys:", list(res.keys()), "total_rows=", res["total_rows"])

with get_connection() as conn:
    print("cases id=1:", conn.execute("SELECT COUNT(*) FROM cases WHERE id=1").fetchone()[0])
    print("hosts case_id=1:", conn.execute("SELECT COUNT(*) FROM hosts WHERE case_id=1").fetchone()[0])
    print("event_disposition_log:", conn.execute("SELECT COUNT(*) FROM event_disposition_log").fetchone()[0])
    print("status_history:", conn.execute("SELECT COUNT(*) FROM status_history").fetchone()[0])
    print("security_events h(1,2):", conn.execute("SELECT COUNT(*) FROM security_events WHERE host_id IN (1,2)").fetchone()[0])
    for t in HOST_TABLES:
        n = conn.execute(f"SELECT COUNT(*) FROM {t} WHERE host_id IN (1,2)").fetchone()[0]
        if n != 0:
            print("LEFTOVER host table", t, n)
    for t in CASE_DIRECT_TABLES:
        n = conn.execute(f"SELECT COUNT(*) FROM {t} WHERE case_id=1").fetchone()[0]
        if n != 0:
            print("LEFTOVER case table", t, n)
    # cross-case precision
    print("PRECISION cases id=2:", conn.execute("SELECT COUNT(*) FROM cases WHERE id=2").fetchone()[0])
    print("PRECISION hosts case_id=2:", conn.execute("SELECT COUNT(*) FROM hosts WHERE case_id=2").fetchone()[0])
    print("PRECISION security_events h(3,4):", conn.execute("SELECT COUNT(*) FROM security_events WHERE host_id IN (3,4)").fetchone()[0])
    for t in HOST_TABLES:
        n = conn.execute(f"SELECT COUNT(*) FROM {t} WHERE host_id IN (3,4)").fetchone()[0]
        if n < 1:
            print("CASE2 UNDER-CLEARED", t, n)
    print("data_purge_log:", conn.execute("SELECT COUNT(*) FROM data_purge_log").fetchone()[0])
    print("audit case_purge:", conn.execute("SELECT COUNT(*) FROM audit_logs WHERE action_type='case_purge'").fetchone()[0])

print("snapshot exists:", __import__("os").path.exists(res["snapshot_path"]))
snap = json.loads(Path(res["snapshot_path"]).read_text(encoding="utf-8"))
print("snap case_id:", snap["case_id"], "name:", snap["case"]["name"])
print("security_events in snap:", "security_events" in snap["tables"])
print("incident_report_audit in snap:", "incident_report_audit" in snap["tables"])
_cleanup_snapshots([1])
print("DONE")
