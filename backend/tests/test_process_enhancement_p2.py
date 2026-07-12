#!/usr/bin/env python3
"""进程检测加强规则集 — P2 验收测试（T14-T18）.

覆盖：
  T14  ProcessInfo Schema 扩展字段（session / memory_sections / state，向后兼容）
  T16  fileless_reflective_injection / script_interpreter_memory_pe /
       amsi_etw_tamper / cross_session_parent_child / injection_window_anomaly /
       process_vanished_between_snapshots（缺数据优雅降级）
  T17  revoked_expired_signature（吊销库空时降级；命中吊销 CA 时告警）
  T15  ProcessEvent 模型 + process_event_consumer（事件摄取/归一化/评估）
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings  # noqa: E402

RULES_DIR = BACKEND_DIR / "app" / "rules"
ENHANCEMENT_PATH = RULES_DIR / "process_enhancement_rules.json"


def _load_rule(name: str) -> dict:
    for r in json.loads(ENHANCEMENT_PATH.read_text(encoding="utf-8")):
        if r["name"] == name:
            return r
    raise KeyError(f"rule not found: {name}")


class DBTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_path = tempfile.mktemp(suffix=".db")
        settings.DB_PATH = cls.db_path
        from app.database import init_db
        init_db()

    @classmethod
    def tearDownClass(cls):
        import os
        try:
            if os.path.exists(cls.db_path):
                os.unlink(cls.db_path)
        except OSError:
            pass


class TestProcessInfoSchema(DBTestBase):
    """T14：ProcessInfo 扩展字段 + 向后兼容（extra='allow'）."""

    def test_new_fields_accepted(self):
        from app.schemas.agent_data import ProcessInfo
        p = ProcessInfo(
            pid=1, name="x.exe", path="C:\\x.exe", session=1,
            memory_sections=[{"injection": True}], state="Running",
        )
        self.assertEqual(p.session, 1)
        self.assertEqual(p.memory_sections, [{"injection": True}])
        self.assertEqual(p.state, "Running")

    def test_backward_compat_extra_fields(self):
        from app.schemas.agent_data import ProcessInfo
        # 历史/采集端新增字段（whitelisted、parent_name）不应抛错
        p = ProcessInfo(pid=2, name="y.exe", whitelisted=True, parent_name="cmd.exe")
        self.assertTrue(p.whitelisted)
        self.assertEqual(p.parent_name, "cmd.exe")
        # 缺省（无扩展字段）仍正常
        p2 = ProcessInfo(pid=3)
        self.assertIsNone(p2.session)


class TestRevokedSignature(DBTestBase):
    """T17：revoked_expired_signature（吊销库空 → 降级；命中 → 告警）."""

    def _set_cache(self, value):
        import app.rules.rule_engine as re_mod
        re_mod._REVOKED_CA_CACHE = value

    def tearDown(self):
        self._set_cache(None)  # 复位，避免影响其它用例

    def test_graceful_when_revoked_store_empty(self):
        from app.rules.rule_engine import RuleEngine
        self._set_cache(None)
        rule = _load_rule("revoked_expired_signature")
        # 吊销库空（revoked_ca.json 默认空）时不应命中、不抛异常
        self.assertFalse(
            RuleEngine.match_rule(
                {"exe_signer": "CN=Some Legit CA"}, rule, global_context={}
            )
        )

    def test_match_when_signer_revoked(self):
        from app.rules.rule_engine import RuleEngine
        self._set_cache({"cn=fake malicious ca"})
        rule = _load_rule("revoked_expired_signature")
        self.assertTrue(
            RuleEngine.match_rule(
                {"exe_signer": "CN=Fake Malicious CA"}, rule, global_context={}
            )
        )

    def test_no_match_when_signer_clean(self):
        from app.rules.rule_engine import RuleEngine
        self._set_cache({"cn=fake malicious ca"})
        rule = _load_rule("revoked_expired_signature")
        self.assertFalse(
            RuleEngine.match_rule(
                {"exe_signer": "CN=Good CA"}, rule, global_context={}
            )
        )


class TestFilelessMemoryInjection(DBTestBase):
    """T16：fileless_reflective_injection（memory_sections 注入痕迹）."""

    def test_match_with_injection_section(self):
        from app.rules.rule_engine import RuleEngine
        rule = _load_rule("fileless_reflective_injection")
        self.assertTrue(
            RuleEngine.match_rule(
                {"memory_sections": [{"injection": True, "base_address": "0x1000"}]},
                rule, global_context={},
            )
        )

    def test_graceful_without_memory_sections(self):
        from app.rules.rule_engine import RuleEngine
        rule = _load_rule("fileless_reflective_injection")
        self.assertFalse(
            RuleEngine.match_rule({"name": "x.exe"}, rule, global_context={})
        )
        self.assertFalse(
            RuleEngine.match_rule(
                {"memory_sections": []}, rule, global_context={}
            )
        )


class TestScriptInterpreterMemoryPe(DBTestBase):
    """T16：script_interpreter_memory_pe（解释器内存 PE）."""

    def test_match_interpreter_with_pe(self):
        from app.rules.rule_engine import RuleEngine
        rule = _load_rule("script_interpreter_memory_pe")
        self.assertTrue(
            RuleEngine.match_rule(
                {"name": "powershell.exe",
                 "memory_sections": [{"pe_in_memory": True}]},
                rule, global_context={},
            )
        )

    def test_no_match_non_interpreter(self):
        from app.rules.rule_engine import RuleEngine
        rule = _load_rule("script_interpreter_memory_pe")
        self.assertFalse(
            RuleEngine.match_rule(
                {"name": "notepad.exe",
                 "memory_sections": [{"pe_in_memory": True}]},
                rule, global_context={},
            )
        )

    def test_graceful_without_memory_sections(self):
        from app.rules.rule_engine import RuleEngine
        rule = _load_rule("script_interpreter_memory_pe")
        self.assertFalse(
            RuleEngine.match_rule({"name": "powershell.exe"}, rule, global_context={})
        )


class TestAmsiEtwTamper(DBTestBase):
    """T16：amsi_etw_tamper（ETW/AMSI 旁路）."""

    def test_match_etw_disable(self):
        from app.rules.rule_engine import RuleEngine
        rule = _load_rule("amsi_etw_tamper")
        self.assertTrue(
            RuleEngine.match_rule(
                {"etw_events": [{"event_type": "etw", "detail": "provider disable"}]},
                rule, global_context={},
            )
        )

    def test_match_amsi_patch(self):
        from app.rules.rule_engine import RuleEngine
        rule = _load_rule("amsi_etw_tamper")
        self.assertTrue(
            RuleEngine.match_rule(
                {"etw_events": [{"event_type": "amsi", "detail": "memory patch tamper"}]},
                rule, global_context={},
            )
        )

    def test_graceful_without_events(self):
        from app.rules.rule_engine import RuleEngine
        rule = _load_rule("amsi_etw_tamper")
        self.assertFalse(
            RuleEngine.match_rule({"name": "x.exe"}, rule, global_context={})
        )


class TestCrossSessionParentChild(DBTestBase):
    """T16：cross_session_parent_child（跨会话/跨用户父子）."""

    def test_match_system_to_interactive(self):
        from app.rules.rule_engine import RuleEngine
        rule = _load_rule("cross_session_parent_child")
        parent = {"pid": 100, "session": 0}
        child = {"pid": 200, "ppid": 100, "session": 1}
        ctx = {"process_map": {100: parent}}
        self.assertTrue(RuleEngine.match_rule(child, rule, global_context=ctx))

    def test_graceful_without_session_field(self):
        from app.rules.rule_engine import RuleEngine
        rule = _load_rule("cross_session_parent_child")
        self.assertFalse(
            RuleEngine.match_rule(
                {"pid": 200, "ppid": 100}, rule, global_context={"process_map": {}}
            )
        )


class TestInjectionWindowAnomaly(DBTestBase):
    """T16：injection_window_anomaly（启动后极短窗口内远线程）."""

    def test_match_within_window(self):
        from datetime import datetime, timedelta

        from app.rules.rule_engine import RuleEngine
        rule = _load_rule("injection_window_anomaly")
        # start_time 须为近期（规则过滤 >3600s 的陈旧进程），用相对当前时间构造
        start = datetime.now() - timedelta(seconds=1)
        evt = start + timedelta(seconds=0.5)
        proc = {
            "start_time": start.strftime("%Y-%m-%d %H:%M:%S"),
            "remote_thread_events": [
                {"timestamp": evt.strftime("%Y-%m-%d %H:%M:%S")},
            ],
        }
        self.assertTrue(RuleEngine.match_rule(proc, rule, global_context={}))

    def test_graceful_without_events(self):
        from app.rules.rule_engine import RuleEngine
        rule = _load_rule("injection_window_anomaly")
        self.assertFalse(
            RuleEngine.match_rule(
                {"start_time": "2026-01-01 00:00:00"}, rule, global_context={}
            )
        )


class TestProcessVanished(DBTestBase):
    """T16：process_vanished_between_snapshots（快照间消失进程）."""

    def test_match_event_only_process(self):
        from app.rules.rule_engine import RuleEngine
        rule = _load_rule("process_vanished_between_snapshots")
        self.assertTrue(
            RuleEngine.match_rule(
                {"seen_in_events": True, "seen_in_snapshot": False},
                rule, global_context={},
            )
        )

    def test_no_match_when_in_snapshot(self):
        from app.rules.rule_engine import RuleEngine
        rule = _load_rule("process_vanished_between_snapshots")
        self.assertFalse(
            RuleEngine.match_rule(
                {"seen_in_events": True, "seen_in_snapshot": True},
                rule, global_context={},
            )
        )


class TestProcessEventPipeline(DBTestBase):
    """T15：ProcessEvent 模型 + process_event_consumer（事件流管道）."""

    def setUp(self):
        # process_events 表 host_id 引用 hosts（外键），先建 case+host
        from app.database import get_connection
        with get_connection() as conn:
            conn.execute("INSERT INTO cases (name) VALUES ('case')", ())
            conn.execute(
                "INSERT INTO hosts (case_id, hostname) VALUES (1, 'h1')", ()
            )
            conn.execute(
                "INSERT INTO hosts (case_id, hostname) VALUES (1, 'h2')", ()
            )
            conn.execute(
                "INSERT INTO hosts (case_id, hostname) VALUES (1, 'h3')", ()
            )

    def test_table_created(self):
        from app.database import DDL_STATEMENTS
        ddl = [d for d in DDL_STATEMENTS if "process_events" in d]
        self.assertTrue(ddl, "process_events 表 DDL 应存在于 DDL_STATEMENTS")

    def test_ingest_and_normalize(self):
        from app.analysis.process_event_consumer import ProcessEventConsumer

        count = ProcessEventConsumer.ingest(1, [
            {"event_type": "process_start", "pid": 10, "ppid": 4,
             "process_name": "weird.exe", "process_path": "C:\\Temp\\weird.exe",
             "command_line": "weird.exe", "start_time": "2026-01-01 00:00:00"},
        ])
        self.assertEqual(count, 1)
        normalized = ProcessEventConsumer.normalize(1)
        self.assertEqual(len(normalized), 1)
        proc = normalized[0]
        self.assertEqual(proc["pid"], 10)
        self.assertEqual(proc["name"], "weird.exe")
        self.assertTrue(proc["seen_in_events"])

    def test_normalize_promotes_detail_fields(self):
        from app.analysis.process_event_consumer import ProcessEventConsumer

        ProcessEventConsumer.ingest(2, [
            {"event_type": "process_start", "pid": 20, "ppid": 4,
             "process_name": "powershell.exe", "process_path": "C:\\Temp\\p.exe",
             "start_time": "2026-01-01 00:00:00",
             "detail": {"memory_sections": [{"pe_in_memory": True}]}},
        ])
        normalized = ProcessEventConsumer.normalize(2)
        self.assertEqual(normalized[0]["memory_sections"], [{"pe_in_memory": True}])

    def test_evaluate_runs_and_detects(self):
        from app.analysis.process_event_consumer import ProcessEventConsumer

        ProcessEventConsumer.ingest(3, [
            {"event_type": "process_start", "pid": 30, "ppid": 4,
             "process_name": "weird.exe", "process_path": "C:\\Temp\\weird.exe",
             "command_line": "weird.exe", "start_time": "2026-01-01 00:00:00"},
        ])
        rules = [_load_rule("unsigned_executable")]
        result = ProcessEventConsumer.evaluate(3, rules)
        # 事件进程无签名信息（exe_is_signed 缺失）→ 视为无签名 → 命中
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["pid"], 30)

    def test_evaluate_graceful_no_events(self):
        from app.analysis.process_event_consumer import ProcessEventConsumer
        # 无事件时 evaluate 应返回空列表且不抛异常（host 999 不存在也无妨，仅 SELECT）
        self.assertEqual(ProcessEventConsumer.evaluate(999, [_load_rule("unsigned_executable")]), [])


if __name__ == "__main__":
    unittest.main()
