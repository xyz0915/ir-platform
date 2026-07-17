"""SyncService 同步服务测试（v2 §3/§6）."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import contextmanager
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.sync_service import (
    CM_TABLE_MAP, SyncService, cm_row_to_canonical, resolve_severity, _fetch_cm_rows,
)


class TestSyncService(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.db_fd)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("CREATE TABLE security_events (id TEXT, host_id INTEGER, event_type TEXT, "
                          "severity TEXT, status TEXT, attack_stage TEXT, matched_rules TEXT, "
                          "attack_chain_id TEXT, ioc_matches TEXT, evidence TEXT, assignee TEXT, "
                          "related_events TEXT, source_collector TEXT, timestamp TEXT, event_key TEXT, "
                          "created_at TEXT, updated_at TEXT)")
        self.conn.execute("CREATE TABLE IF NOT EXISTS abnormal_processes "
                          "(id INTEGER, host_id INTEGER, process_name TEXT, pid INTEGER, "
                          "severity TEXT, risk_score INTEGER, reason TEXT, rule_name TEXT, "
                          "details TEXT, command_line TEXT, parent_name TEXT, attack_path TEXT)")
        self.conn.execute("CREATE TABLE IF NOT EXISTS persistence_items "
                          "(id INTEGER, host_id INTEGER, type TEXT, name TEXT, command TEXT, "
                          "location TEXT, user TEXT, is_suspicious INTEGER, reason TEXT, details TEXT)")
        self.conn.execute("CREATE TABLE IF NOT EXISTS incident_correlations "
                          "(id INTEGER, title TEXT, description TEXT, severity TEXT, host_ids TEXT, "
                          "kill_chain TEXT, status TEXT)")
        self.conn.execute("CREATE TABLE IF NOT EXISTS file_hashes "
                          "(id INTEGER, host_id INTEGER, file_path TEXT, file_name TEXT, "
                          "sha256 TEXT, is_signed INTEGER, signer TEXT)")
        self.conn.execute("CREATE TABLE IF NOT EXISTS suspicious_startup_items "
                          "(id INTEGER, host_id INTEGER, name TEXT, command TEXT, location TEXT, "
                          "type TEXT, user TEXT, reason TEXT, rule_name TEXT, severity TEXT)")
        # Sample data
        self.conn.execute("INSERT INTO abnormal_processes VALUES "
                          "(1,29,'evil.exe',123,'high',85,'orphan process','orphan_process',"
                          "'{}','evil.exe -enc X','explorer.exe','execution')")
        self.conn.execute("INSERT INTO abnormal_processes VALUES "
                          "(2,29,'normal.exe',456,'info',0,'legit process','none','{}','clean.exe','svchost.exe','')")
        self.conn.execute("INSERT INTO persistence_items VALUES "
                          "(1,29,'registry','RunKey','evil.exe','HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run','admin',1,'suspicious run key','{}')")
        self.conn.execute("INSERT INTO incident_correlations VALUES "
                          "(1,'持久化驻留','发现异常持久化','high','[\"29\"]',NULL,'open')")
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        os.unlink(self.db_path)

    @contextmanager
    def _patch(self):
        @contextmanager
        def _fake():
            yield self.conn
        with patch("app.services.sync_service.get_connection", _fake):
            yield

    def test_cm_table_map_has_all_expected(self):
        names = set(CM_TABLE_MAP.keys())
        for t in ["abnormal_processes", "persistence_items", "suspicious_startup_items",
                   "file_hashes", "incident_correlations"]:
            self.assertIn(t, names)

    def test_resolve_severity_with_field(self):
        row = {"severity": "high", "risk_score": 85}
        sev = resolve_severity(row, "severity")
        self.assertEqual(sev, "high")
        sev2 = resolve_severity(row, None)
        self.assertEqual(sev2, "medium")  # no field -> default

    def test_cm_row_to_canonical_abnormal(self):
        with self.conn:
            rows = self.conn.execute("SELECT * FROM abnormal_processes WHERE id=1").fetchall()
        cfg = CM_TABLE_MAP["abnormal_processes"]
        ce = cm_row_to_canonical("abnormal_processes", dict(rows[0]), 29, cfg)
        self.assertEqual(ce.event_uid, "cm:abnormal_processes:1")
        self.assertEqual(ce.source, "cm")
        self.assertEqual(ce.event_type, "process_start")
        self.assertEqual(ce.category, "behavior")
        self.assertEqual(ce.severity, "high")
        self.assertEqual(ce.risk_score, 85)
        self.assertIn("process_name", ce.evidence)
        self.assertEqual(ce.evidence["process_name"], "evil.exe")

    def test_cm_row_to_canonical_persistence_suspicious(self):
        with self.conn:
            rows = self.conn.execute("SELECT * FROM persistence_items WHERE id=1").fetchall()
        cfg = CM_TABLE_MAP["persistence_items"]
        ce = cm_row_to_canonical("persistence_items", dict(rows[0]), 29, cfg)
        self.assertEqual(ce.event_type, "persistence_register")
        self.assertEqual(ce.category, "persistence")

    def test_fetch_cm_rows_filters_by_severity(self):
        rows = _fetch_cm_rows(self.conn, "abnormal_processes", 29, CM_TABLE_MAP["abnormal_processes"])
        # Only row with severity >= medium (id=1 high) -> 1 result; id=2 has severity=info, filtered out
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], 1)

    def test_sync_cm_to_ac_readonly(self):
        """验证 sync_cm_to_ac 实际的 DB upsert 行为（不含 host_ids 特别处理）。"""
        with self._patch():
            result = SyncService.sync_cm_to_ac(29)
        self.assertGreater(result["synced"], 0,
                           msg=f"sync errors: {result.get('errors')}, cm_total={result.get('total_cm_rows')}")
        # Check that security_events now has the new events
        with self._patch():
            count = [r["id"] for r in self.conn.execute(
                "SELECT id FROM security_events WHERE id LIKE 'cm:%'").fetchall()]
        self.assertGreater(len(count), 0)
        self.assertIn("cm:abnormal_processes:1", count)

    def test_backfill_structure(self):
        with self._patch():
            result = SyncService.backfill(29, source="cm")
        self.assertIn("synced", result)
        self.assertIn("total_cm_rows", result)


if __name__ == "__main__":
    unittest.main()
