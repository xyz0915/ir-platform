"""Debug sync_cm_to_ac test failure."""
import sqlite3, json, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from contextlib import contextmanager
from unittest.mock import patch
from app.services.sync_service import SyncService, CM_TABLE_MAP, _fetch_cm_rows

db = sqlite3.connect(':memory:')
db.row_factory = sqlite3.Row
db.execute('CREATE TABLE security_events (id TEXT, host_id INTEGER, event_type TEXT, severity TEXT, status TEXT, attack_stage TEXT, matched_rules TEXT, attack_chain_id TEXT, ioc_matches TEXT, evidence TEXT, assignee TEXT, related_events TEXT, source_collector TEXT, created_at TEXT, updated_at TEXT)')
db.execute('CREATE TABLE IF NOT EXISTS abnormal_processes (id INTEGER, host_id INTEGER, process_name TEXT, pid INTEGER, severity TEXT, risk_score INTEGER, reason TEXT, rule_name TEXT, details TEXT, command_line TEXT, parent_name TEXT, attack_path TEXT)')
db.execute('CREATE TABLE IF NOT EXISTS persistence_items (id INTEGER, host_id INTEGER, type TEXT, name TEXT, command TEXT, location TEXT, user TEXT, is_suspicious INTEGER, reason TEXT, details TEXT)')
db.execute('CREATE TABLE IF NOT EXISTS incident_correlations (id INTEGER, title TEXT, description TEXT, severity TEXT, host_ids TEXT, kill_chain TEXT, status TEXT)')
db.execute('CREATE TABLE IF NOT EXISTS file_hashes (id INTEGER, host_id INTEGER, file_path TEXT, file_name TEXT, sha256 TEXT, is_signed INTEGER, signer TEXT)')
db.execute('CREATE TABLE IF NOT EXISTS suspicious_startup_items (id INTEGER, host_id INTEGER, name TEXT, command TEXT, location TEXT, type TEXT, user TEXT, reason TEXT, rule_name TEXT, severity TEXT)')
db.execute("INSERT INTO abnormal_processes VALUES (1,29,'evil.exe',123,'high',85,'orphan process','orphan_process','{}','evil.exe -enc X','explorer.exe','execution')")
db.execute("INSERT INTO abnormal_processes VALUES (2,29,'normal.exe',456,'info',0,'legit process','none','{}','clean.exe','svchost.exe','')")
db.execute("INSERT INTO persistence_items VALUES (1,29,'registry','RunKey','evil.exe',r'HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Run','admin',1,'suspicious run key','{}')")
db.execute("INSERT INTO incident_correlations VALUES (1,'持久化驻留','发现异常持久化','high','[\"29\"]',NULL,'open')")
db.commit()

@contextmanager
def _fake():
    yield db

with patch('app.services.sync_service.get_connection', _fake):
    for t, cfg in CM_TABLE_MAP.items():
        try:
            rows = _fetch_cm_rows(db, t, 29, cfg)
            print(f'{t}: {len(rows)} rows fetched')
            for r in rows:
                print(f'  id={r["id"]}')
        except Exception as e:
            print(f'{t}: ERROR {e}')
    result = SyncService.sync_cm_to_ac(29)
    print('Result:', json.dumps(result, ensure_ascii=False, default=str))
    print('SE rows after:', [(r["id"], r["event_type"]) for r in db.execute('SELECT id, event_type FROM security_events').fetchall()])
