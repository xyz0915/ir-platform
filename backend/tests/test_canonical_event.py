"""CanonicalEvent 规范事件模型测试（v2 §3）."""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.canonical_event import CanonicalEvent, CanonicalEventDisplay


class TestCanonicalEvent(unittest.TestCase):
    def test_basic_creation(self):
        ce = CanonicalEvent(event_uid="ac:e1", source="ac", source_event_id="e1", host_id=1)
        self.assertEqual(ce.event_uid, "ac:e1")
        self.assertEqual(ce.category, "unknown")   # 默认
        self.assertEqual(ce.severity, "medium")     # 默认
        self.assertEqual(ce.status, "pending")      # 默认
        self.assertEqual(ce.lifecycle_state, "collected")

    def test_invalid_status_normalized(self):
        ce = CanonicalEvent(event_uid="ac:e2", source="ac", source_event_id="e2", host_id=1, status="bad_status")
        self.assertEqual(ce.status, "pending")  # normalized to default

    def test_invalid_severity_normalized(self):
        ce = CanonicalEvent(event_uid="ac:e3", source="ac", source_event_id="e3", host_id=1, severity="ultra")
        self.assertEqual(ce.severity, "medium")

    def test_event_uid_fallback(self):
        ce = CanonicalEvent(event_uid="", source="ac", source_event_id="auto-id", host_id=1)
        self.assertEqual(ce.event_uid, "ac:auto-id")

    def test_to_dict_structure(self):
        ce = CanonicalEvent(event_uid="ac:e4", source="ac", source_event_id="e4", host_id=2,
                            event_type="process_start", severity="high",
                            evidence={"pid": 123, "name": "evil.exe"})
        d = ce.to_dict()
        self.assertEqual(d["event_uid"], "ac:e4")
        self.assertEqual(d["event_type"], "process_start")
        self.assertEqual(d["severity"], "high")
        self.assertIn("pid", d["evidence"])

    def test_display_dataclass(self):
        d = CanonicalEventDisplay(required=[{"key": "id", "value": "e1"}],
                                  auxiliary=[],
                                  evidence_views={"normalized": {}, "raw": {}, "raw_source": "test"})
        self.assertEqual(len(d.required), 1)
        self.assertEqual(d.required[0]["key"], "id")
        self.assertEqual(d.evidence_views["raw_source"], "test")


if __name__ == "__main__":
    unittest.main()
