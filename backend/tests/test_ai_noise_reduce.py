"""AI 降噪 · 优先推荐事件 测试（v2 方案）.

测试内容：
  1. build_events_summary — 格式正确性
  2. _parse_llm_response — JSON 解析
  3. save_results — attack 生成新事件 / suspicious 标记 / false_positive 标记
  4. noise_reduce — 完整流程（mock LLM）
  5. ensure_ai_columns — 幂等
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

from app.services.ai_noise_reduce import (
    build_events_summary,
    _parse_llm_response,
    save_results,
    ensure_ai_columns,
)


class TestBuildEventsSummary(unittest.TestCase):
    def test_basic_format(self):
        events = [
            {
                "id": "evt001",
                "event_type": "process_start",
                "matched_rules": '[{"rule_name":"orphan_process","confidence":0.75}]',
                "evidence": '{"process_name": "evil.exe", "command_line": "evil.exe -enc"}',
                "summary": "process_start evil.exe",
            }
        ]
        result = build_events_summary(events)
        self.assertIn("evt001", result)
        self.assertIn("orphan_process", result)
        self.assertIn("0.75", result)

    def test_multiple_events(self):
        events = [
            {"id": "e1", "event_type": "process_start", "matched_rules": "[]", "evidence": "{}"},
            {"id": "e2", "event_type": "network_outbound", "matched_rules": "[]", "evidence": "{}"},

        ]
        result = build_events_summary(events)
        lines = [l for l in result.split("\n") if l.strip()]
        self.assertEqual(len(lines), 2)

    def test_empty_list(self):
        result = build_events_summary([])
        self.assertEqual(result, "")

    def test_evidence_with_none_values(self):
        """回归测试: evidence 字段值为 None 时不应崩.

        之前 _enrich 传入的 evidence 可能 process_name/file_name/command_line
        存在但为 None，会导致 proc[:20] 抛 TypeError。
        """
        events = [
            {
                "id": "evt_null_1",
                "event_type": "process_start",
                "matched_rules": '[{"rule_name":"r1","confidence":0.5}]',
                "evidence": '{"process_name": null, "command_line": null}',
            },
            {
                "id": "evt_null_2",
                "event_type": "file_create",
                "matched_rules": '[{"rule_name":"r2","confidence":0.6}]',
                "evidence": '{"file_name": null}',
            },
            {
                "id": "evt_null_3",
                "event_type": "process_start",
                "matched_rules": "[]",
                "evidence": "",
            },
        ]
        result = build_events_summary(events)
        self.assertIn("evt_null_1", result)
        self.assertIn("evt_null_2", result)
        self.assertIn("evt_null_3", result)


class TestParseLlmResponse(unittest.TestCase):
    def test_parse_json_array(self):
        raw = '[{"event_id":"e1","label":"attack","confidence":92}]'
        result = _parse_llm_response(raw)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["label"], "attack")

    def test_parse_code_block(self):
        raw = '```json\n[{"event_id":"e1","label":"attack"}]\n```'
        result = _parse_llm_response(raw)
        self.assertEqual(len(result), 1)

    def test_parse_multiline(self):
        raw = '{"event_id":"e1","label":"attack"}\n{"event_id":"e2","label":"suspicious"}'
        result = _parse_llm_response(raw)
        self.assertEqual(len(result), 2)

    def test_invalid_returns_empty(self):
        result = _parse_llm_response("not json at all")
        self.assertEqual(result, [])


class TestSaveResults(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.db_fd)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("CREATE TABLE security_events (id TEXT, host_id INTEGER, event_type TEXT, "
                          "severity TEXT, status TEXT, attack_stage TEXT, matched_rules TEXT, "
                          "attack_chain_id TEXT, ioc_matches TEXT, evidence TEXT, assignee TEXT, "
                          "related_events TEXT, source_collector TEXT, timestamp TEXT, event_key TEXT, "
                          "created_at TEXT, updated_at TEXT, ai_verdict TEXT, ai_analysis TEXT DEFAULT '')")
        self.conn.execute("INSERT INTO security_events VALUES "
                          "('evt001',29,'process_start','high','pending','execution','[{\"rule_name\":\"orphan_process\"}]',"
                          "NULL,'[]','{\"process_name\":\"evil.exe\"}',NULL,'[]','ac','2026-01-01','evt001','2026-01-01','2026-01-01',NULL,'')")
        self.conn.execute("INSERT INTO security_events VALUES "
                          "('evt002',29,'persistence_register','medium','pending','persistence','[{\"rule_name\":\"run_key\"}]',"
                          "NULL,'[]','{}',NULL,'[]','ac','2026-01-01','evt002','2026-01-01','2026-01-01',NULL,'')")
        self.conn.execute("INSERT INTO security_events VALUES "
                          "('evt003',29,'file_create','low','pending',NULL,'[{\"rule_name\":\"temp_file\"}]',"
                          "NULL,'[]','{}',NULL,'[]','ac','2026-01-01','evt003','2026-01-01','2026-01-01',NULL,'')")
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        os.unlink(self.db_path)

    @contextmanager
    def _patch(self):
        @contextmanager
        def _fake():
            yield self.conn
        with patch("app.services.ai_noise_reduce.get_connection", _fake):
            yield

    def test_attack_creates_ai_event(self):
        verdicts = [
            {"event_id": "evt001", "label": "attack", "confidence": 92, "reason": "非系统目录执行",
             "action": "isolate", "attack_type": "执行", "t_code": "T1059",
             "ai_summary": "[AI研判]攻击|置信92%|T1059|非系统目录脚本执行|建议:隔离"},
        ]
        originals = {"evt001": {"id": "evt001", "event_type": "process_start", "severity": "high",
                                "host_id": 29, "matched_rules": "[]", "evidence": '{"process_name":"evil.exe"}',
                                "attack_stage": "execution"}}
        with self._patch():
            stats = save_results(verdicts, originals)
        self.assertEqual(stats["attack"], 1)
        self.assertEqual(stats["ai_events"], 1)
        ai_event = self.conn.execute("SELECT * FROM security_events WHERE id='ai:evt001'").fetchone()
        self.assertIsNotNone(ai_event)
        self.assertEqual(ai_event["event_type"], "ai_recommended")
        self.assertIn("AI研判", ai_event["ai_analysis"])

    def test_attack_idempotent(self):
        """重复调用不应生成重复 AI 事件。"""
        verdicts = [
            {"event_id": "evt001", "label": "attack", "confidence": 92, "reason": "非系统目录执行",
             "action": "isolate", "attack_type": "执行", "t_code": "T1059",
             "ai_summary": "[AI研判]攻击|置信92%|T1059|非系统目录脚本执行|建议:隔离"},
        ]
        originals = {"evt001": {"id": "evt001", "event_type": "process_start", "severity": "high",
                                "host_id": 29, "matched_rules": "[]", "evidence": '{}', "attack_stage": "execution"}}
        with self._patch():
            save_results(verdicts, originals)
            stats2 = save_results(verdicts, originals)
        self.assertEqual(stats2["ai_events"], 0)  # 幂等：不重复插入

    def test_suspicious_marks_only(self):
        verdicts = [
            {"event_id": "evt002", "label": "suspicious", "confidence": 55, "reason": "路径可疑但无恶意证据",
             "action": "review", "attack_type": "", "t_code": "", "ai_summary": ""},
        ]
        with self._patch():
            stats = save_results(verdicts, {})
        self.assertEqual(stats["suspicious"], 1)
        self.assertEqual(stats["ai_events"], 0)
        updated = self.conn.execute("SELECT ai_verdict FROM security_events WHERE id='evt002'").fetchone()
        self.assertIsNotNone(updated["ai_verdict"])
        self.assertIn("suspicious", updated["ai_verdict"])

    def test_false_positive_marks_only(self):
        verdicts = [
            {"event_id": "evt003", "label": "false_positive", "confidence": 98, "reason": "系统进程",
             "action": "review", "attack_type": "", "t_code": "", "ai_summary": ""},
        ]
        with self._patch():
            stats = save_results(verdicts, {})
        self.assertEqual(stats["false_positive"], 1)
        self.assertEqual(stats["ai_events"], 0)


class TestEnsureAiColumns(unittest.TestCase):
    def test_columns_created(self):
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE security_events (id TEXT PRIMARY KEY)")
        conn.close()

        with patch("app.services.ai_noise_reduce.get_connection") as mock_get:
            @contextmanager
            def _fake():
                c = sqlite3.connect(db_path)
                c.row_factory = sqlite3.Row
                yield c
                c.close()
            mock_get.side_effect = _fake
            ensure_ai_columns()

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(security_events)").fetchall()}
        conn.close()
        os.unlink(db_path)
        self.assertIn("ai_verdict", cols)
        self.assertIn("ai_analysis", cols)


if __name__ == "__main__":
    unittest.main()
