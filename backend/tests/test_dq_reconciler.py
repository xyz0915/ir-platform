"""DQReconciler 数据质量监控测试（v2 §3/§7）."""
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

from app.services.dq_monitor import DQReconciler


class TestDQReconciler(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.db_fd)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("CREATE TABLE security_events (id TEXT, host_id INTEGER, event_type TEXT, "
                          "severity TEXT, status TEXT, attack_stage TEXT, matched_rules TEXT, "
                          "attack_chain_id TEXT, ioc_matches TEXT, related_events TEXT)")
        self.conn.execute("INSERT INTO security_events VALUES "
                          "('e1',29,'process_start','high','investigating','execution','[{\"rule_id\":1}]','chain-1','[\"8.8.8.8\"]','[]')")
        self.conn.execute("INSERT INTO security_events VALUES "
                          "('e2',29,'network_outbound','medium','pending','c2','[]',NULL,'[]','[]')")
        self.conn.execute("INSERT INTO security_events VALUES "
                          "('e3',29,'dns_query','low','pending',NULL,'[]',NULL,'[]','[]')")
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        os.unlink(self.db_path)

    @contextmanager
    def _patch(self):
        @contextmanager
        def _fake():
            yield self.conn
        with patch("app.services.dq_monitor.get_connection", _fake):
            yield

    def test_check_field_fill(self):
        with self._patch():
            rep = DQReconciler.check_field_fill(29)
        self.assertEqual(rep["total_events"], 3)
        self.assertEqual(rep["events_with_missing"], 2)  # e2 (no matched), e3 (no attack_stage, no matched)

    def test_check_field_fill_all_present(self):
        self.conn.execute("INSERT INTO security_events VALUES "
                          "('e4',29,'process_start','high','resolved','execution','[{\"rule_id\":2}]','chain-2','[]','[\"e1\"]')")
        self.conn.commit()
        with self._patch():
            rep = DQReconciler.check_field_fill(29)
        self.assertEqual(rep["total_events"], 4)
        # 4 events / 7 fields = 28 slots; e2/e3 missing some → rate ~0.71, ensure >0.5
        self.assertGreater(rep["overall_rate"], 0.5)

    def test_metrics_returns_structure(self):
        with self._patch():
            m = DQReconciler.metrics()
        self.assertIn("total_events", m)
        self.assertIn("match_rate", m)
        self.assertEqual(m["total_events"], 3)
        self.assertAlmostEqual(m["match_rate"], 0.3333, places=4)

    def test_coverage_requires_raw_json(self):
        # Without raw JSON, coverage returns error — mock read_raw_json to return None
        with patch("app.services.import_service.ImportService.read_raw_json", return_value=None):
            cov = DQReconciler.check_coverage(29)
        self.assertIn("error", cov)

    def test_divergence_structure(self):
        with self._patch():
            div = DQReconciler.check_divergence(29)
        self.assertEqual(div["host_id"], 29)
        self.assertEqual(div["ac_event_count"], 3)
        self.assertIn("cm_detail", div)
        self.assertIn("divergence", div)


if __name__ == "__main__":
    unittest.main()
