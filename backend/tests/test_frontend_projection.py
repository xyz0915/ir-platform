"""前端字段投影 / 证据双视图 / 数据质量监控 测试（v2.1）.

验证：
  - build_event_summary 生成人话摘要（必填「摘要」字段）。
  - project_event 输出必填 14 项 + 辅助 9 项。
  - 证据详情双视图：范式化视图（结构化）+ 完整原始数据（host raw JSON）。
  - get_event_display 注入融合场景。
  - DQMonitor.check_field_fill 计算必填字段填充率。

使用方法:
    pytest backend/tests/test_frontend_projection.py -v
"""

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

from app.services.event_enrichment import build_event_summary
from app.services.frontend_projection import FrontendProjection, project_event, get_event_display, REQUIRED_FIELDS, AUXILIARY_FIELDS
from app.services.dq_monitor import check_field_fill
from app.services.canonical_event import CanonicalEvent


class TestFrontendProjection(unittest.TestCase):
    def setUp(self):
        # 原始采集 JSON（用于视图B）
        self.raw_fd, self.raw_path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(self.raw_fd, "w") as f:
            json.dump({"processes": [{"process_name": "evil.exe", "pid": 123}],
                       "network_connections": []}, f)

        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.db_fd)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("CREATE TABLE cases (id INTEGER PRIMARY KEY, name TEXT, case_number TEXT)")
        self.conn.execute("CREATE TABLE hosts (id INTEGER PRIMARY KEY, case_id INTEGER, hostname TEXT, ip_address TEXT, raw_json_path TEXT)")
        self.conn.execute("""CREATE TABLE security_events (
            id TEXT PRIMARY KEY, timestamp TEXT, host_id INTEGER, event_type TEXT,
            severity TEXT, source_collector TEXT, event_key TEXT, attack_chain_id TEXT,
            attack_stage TEXT, ioc_matches TEXT, evidence TEXT, status TEXT,
            assignee TEXT, related_events TEXT, matched_rules TEXT, created_at TEXT, updated_at TEXT)""")
        self.conn.execute("CREATE TABLE incident_correlations (id INTEGER PRIMARY KEY, title TEXT, host_ids TEXT)")
        self.conn.execute("INSERT INTO cases VALUES (8,'windows应急','CASE-0008')")
        self.conn.execute("INSERT INTO hosts VALUES (29,8,'WIN-29','10.0.0.29',?)", (self.raw_path,))
        self.conn.execute("""INSERT INTO security_events VALUES (
            'evt001','2026-07-11 23:10:30',29,'process_start','high','process','k1',
            'chain-1','execution','["8.8.8.8"]',
            '{"process_name":"evil.exe","pid":123,"parent_name":"explorer.exe","command_line":"evil.exe -enc X"}',
            'investigating','alice','["evt002"]',
            '[{"rule_id":11,"rule_name":"orphan_process","rule_type":"behavior","severity":"high","confidence":0.75,"matched_fields":{}}]',
            '2026-07-11 23:10:30','2026-07-11 23:10:30')""")
        self.conn.execute("INSERT INTO incident_correlations VALUES (1,'持久化驻留','[\"29\"]')")
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        os.unlink(self.db_path)
        os.unlink(self.raw_path)

    @contextmanager
    def _patch(self):
        @contextmanager
        def _fake():
            yield self.conn
        # frontend_projection / dq_monitor 均通过 `from app.database import get_connection`
        # 绑定了各自的 get_connection 名称，需分别 patch 其导入点。
        with patch("app.services.frontend_projection.get_connection", _fake), \
             patch("app.services.dq_monitor.get_connection", _fake):
            yield

    # ── 摘要字段（必填）─────────────────────────────────────────────

    def test_build_summary_process(self):
        ev = {"event_type": "process_start", "severity": "high", "host_id": 29,
              "evidence": {"process_name": "evil.exe", "pid": 123, "parent_name": "explorer.exe"}}
        s = build_event_summary(ev)
        self.assertIn("evil.exe", s)
        self.assertIn("启动", s)

    def test_build_summary_network(self):
        ev = {"event_type": "network_outbound", "severity": "high", "host_id": 29,
              "evidence": {"remote_address": "185.220.101.1", "remote_port": 4444, "protocol": "tcp"}}
        s = build_event_summary(ev)
        self.assertIn("185.220.101.1", s)

    def test_build_summary_fallback(self):
        ev = {"event_type": "unknown_x", "severity": "info", "host_id": 29, "evidence": {}}
        s = build_event_summary(ev)
        self.assertTrue(s)  # 降级拼接，不为空

    # ── 投影结构 ───────────────────────────────────────────────────

    def test_projection_field_counts(self):
        ev = {"id": "evt001", "host_id": 29, "hostname": "WIN-29", "event_type": "process_start",
              "severity": "high", "attack_stage": "execution", "status": "investigating",
              "source_collector": "process", "attack_chain_id": "chain-1",
              "ioc_matches": '["8.8.8.8"]', "matched_rules": '[{"rule_name":"orphan_process"}]',
              "timestamp": "2026-07-11 23:10:30",
              "evidence": {"process_name": "evil.exe", "pid": 123, "parent_name": "explorer.exe"}}
        proj = project_event(ev, self.raw_path)
        self.assertEqual(len(proj["required"]), len(REQUIRED_FIELDS))   # 14
        self.assertEqual(len(proj["auxiliary"]), len(AUXILIARY_FIELDS))  # 9
        req_keys = {r["key"] for r in proj["required"]}
        self.assertIn("summary", req_keys)
        self.assertIn("risk_score", req_keys)
        # 摘要必填项非空
        summary_val = next(r["value"] for r in proj["required"] if r["key"] == "summary")
        self.assertTrue(summary_val)

    # ── 证据双视图 ─────────────────────────────────────────────────

    def test_evidence_dual_view(self):
        ev = {"id": "evt001", "host_id": 29, "hostname": "WIN-29", "event_type": "process_start",
              "severity": "high", "attack_stage": "execution", "status": "investigating",
              "source_collector": "process", "attack_chain_id": "chain-1",
              "ioc_matches": '["8.8.8.8"]', "matched_rules": '[]',
              "timestamp": "2026-07-11 23:10:30",
              "evidence": {"process_name": "evil.exe", "pid": 123}}
        proj = project_event(ev, self.raw_path)
        views = proj["evidence_views"]
        self.assertIn("normalized", views)
        self.assertIn("raw", views)
        self.assertIn("raw_source", views)
        # 视图A = 结构化 evidence
        self.assertEqual(views["normalized"]["process_name"], "evil.exe")
        # 视图B = host raw JSON 中的 processes 块
        self.assertEqual(views["raw"][0]["process_name"], "evil.exe")
        self.assertIn("host_raw_json", views["raw_source"])

    def test_evidence_dual_view_fallback(self):
        """raw_json_path 不可用时回退为 stored_evidence。"""
        ev = {"id": "evt002", "host_id": 29, "hostname": "WIN-29", "event_type": "process_start",
              "severity": "high", "attack_stage": "execution", "status": "investigating",
              "source_collector": "process", "attack_chain_id": None,
              "ioc_matches": '[]', "matched_rules": '[]',
              "timestamp": "2026-07-11 23:10:30",
              "evidence": {"process_name": "x.exe"}}
        proj = project_event(ev, "/nonexistent/path.json")
        views = proj["evidence_views"]
        self.assertEqual(views["raw_source"], "stored_evidence")
        self.assertEqual(views["raw"]["process_name"], "x.exe")

    # ── 展示端点（含融合场景注入）──────────────────────────────────

    def test_get_event_display(self):
        with self._patch():
            result = get_event_display("evt001")
        self.assertIsNotNone(result)
        proj = result["projection"]
        self.assertEqual(len(proj["required"]), 14)
        # 融合场景由 incident_correlations 反查注入
        fusion = next((a["value"] for a in proj["auxiliary"] if a["key"] == "fusion_scene"), None)
        self.assertEqual(fusion, "持久化驻留")

    # ── DQMonitor 字段填充率 ───────────────────────────────────────

    def test_field_fill(self):
        with self._patch():
            rep = check_field_fill(29)
        self.assertEqual(rep["total_events"], 1)
        self.assertEqual(rep["events_with_missing"], 0)
        self.assertAlmostEqual(rep["overall_rate"], 1.0)
        self.assertIn("matched_rules", rep["fields"])


class TestFrontendProjectionClass(unittest.TestCase):
    """验证 FrontendProjection 类化接口 (v2 §3) 与 CanonicalEvent 配合。"""

    def test_project_from_canonical(self):
        ce = CanonicalEvent(
            event_uid="ac:test-cls-1", source="ac", source_event_id="test-cls-1",
            host_id=1, event_type="process_start", severity="high",
            timestamp="2026-07-11T23:10:30",
            evidence={"process_name": "evil.exe", "pid": 123, "command_line": "evil.exe -enc X"},
        )
        disp = FrontendProjection.project(ce)
        self.assertEqual(len(disp.required), 14)
        self.assertEqual(len(disp.auxiliary), 9)
        req_keys = {r["key"] for r in disp.required}
        self.assertIn("summary", req_keys)
        self.assertIn("risk_score", req_keys)

    def test_project_via_event_dict(self):
        ce = CanonicalEvent(
            event_uid="ac:test-cls-2", source="ac", source_event_id="test-cls-2",
            host_id=1, event_type="dns_query", severity="low",
            timestamp="2026-07-11T23:10:30",
            evidence={"query_name": "evil.example.com"},
        )
        disp = FrontendProjection.project(ce)
        self.assertEqual(len(disp.required), 14)
        summary_val = next(r["value"] for r in disp.required if r["key"] == "summary")
        self.assertTrue(summary_val)
        self.assertIn("evil.example.com", summary_val)

    def test_evidence_views_default(self):
        ce = CanonicalEvent(
            event_uid="ac:test-cls-3", source="ac", source_event_id="test-cls-3",
            host_id=1, event_type="process_start", severity="medium",
            evidence={"process_name": "x.exe"},
        )
        disp = FrontendProjection.project(ce)
        self.assertIn("normalized", disp.evidence_views)
        self.assertIn("raw", disp.evidence_views)
        self.assertEqual(disp.evidence_views["raw_source"], "stored_evidence")


if __name__ == "__main__":
    unittest.main()
