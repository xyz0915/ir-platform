#!/usr/bin/env python3
"""P2 进程检测加强规则 — 后端链路可行性 PoC 集成测试（T-P2-1 ~ T-P2-4）.

目标：证明「只要数据到位，7 条 P2 规则能真实命中」——端到端走
RuleEngine.evaluate / ProcessEventConsumer.evaluate / AnomalyDetector.detect_processes，
断言 7 条规则真实命中且 severity 正确；反向用例返回空且不崩。

覆盖：
  T-P2-1  E1-E7 正向用例 + R1-R7 反向用例（RuleEngine + ProcessEventConsumer 集成层）
  T-P2-2  revoked_ca.json 文件级吊销库加载链路（写入→重读→还原）
  T-P2-3  新增端点 POST /api/hosts/{host_id}/process-events（薄封装，落库→消费打通）
  T-P2-4  快照双模集成验证（Mode A 即激活 P2：无需事件管线）
"""

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings  # noqa: E402

RULES_DIR = BACKEND_DIR / "app" / "rules"
ENHANCEMENT_PATH = RULES_DIR / "process_enhancement_rules.json"
REVOKED_CA_PATH = RULES_DIR / "revoked_ca.json"

# 7 条 P2 规则 name（与 process_enhancement_rules.json 严格一致）
P2_RULE_NAMES = [
    "fileless_reflective_injection",
    "script_interpreter_memory_pe",
    "amsi_etw_tamper",
    "cross_session_parent_child",
    "injection_window_anomaly",
    "process_vanished_between_snapshots",
    "revoked_expired_signature",
]


def _load_rule(name: str) -> dict:
    """从 process_enhancement_rules.json 读取指定规则 dict（复用既有测试思路）."""
    for r in json.loads(ENHANCEMENT_PATH.read_text(encoding="utf-8")):
        if r["name"] == name:
            return r
    raise KeyError(f"rule not found: {name}")


def _load_p2_rules() -> list:
    """加载全部 7 条 P2 规则 dict."""
    return [_load_rule(n) for n in P2_RULE_NAMES]


class DBTestBase(unittest.TestCase):
    """自建临时 DB 基类（与 test_process_enhancement_p2.py 同构）."""

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

    def _ensure_host(self, hid: int) -> None:
        """幂等建 case(1) + host(hid)，供 consumer/endpoint 用例满足外键约束."""
        from app.database import get_connection
        with get_connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO cases (id, name) VALUES (1, 'poc-case')", ()
            )
            conn.execute(
                "INSERT OR IGNORE INTO hosts (id, case_id, hostname) VALUES (?, 1, ?)",
                (hid, f"poc-host-{hid}"),
            )

    def _reset_revoked_cache(self) -> None:
        """复位模块级吊销缓存（避免影响其它用例）."""
        import app.rules.rule_engine as re_mod
        re_mod._REVOKED_CA_CACHE = None


class TestP2AgentForward(DBTestBase):
    """T-P2-1 正向用例：E1-E7（7 条规则真实命中 + severity 正确）."""

    def _assert_hit(self, matches, rule_name, severity):
        hit = next(
            (m for m in matches if m["rule_name"] == rule_name), None
        )
        self.assertIsNotNone(hit, f"规则 {rule_name} 应命中")
        self.assertEqual(
            hit["severity"], severity,
            f"规则 {rule_name} severity 应为 {severity}，实际 {hit['severity']}",
        )

    # ── E1 fileless_reflective_injection (critical) ──
    def test_e1_fileless_reflective_injection(self):
        from app.rules.rule_engine import RuleEngine
        rule = _load_rule("fileless_reflective_injection")
        matches = RuleEngine.evaluate(
            [{"pid": 1, "memory_sections": [{"injection": True, "base_address": "0x1000"}]}],
            [rule], global_context={},
        )
        self._assert_hit(matches, "fileless_reflective_injection", "critical")

    # ── E2 script_interpreter_memory_pe (high) ──
    def test_e2_script_interpreter_memory_pe(self):
        from app.rules.rule_engine import RuleEngine
        rule = _load_rule("script_interpreter_memory_pe")
        matches = RuleEngine.evaluate(
            [{"pid": 2, "name": "powershell.exe", "memory_sections": [{"pe_in_memory": True}]}],
            [rule], global_context={},
        )
        self._assert_hit(matches, "script_interpreter_memory_pe", "high")

    # ── E3 amsi_etw_tamper (high) —— 走 ProcessEventConsumer ──
    # 注：consumer.normalize 仅聚合 event_type=="process_start" 的事件，
    # 故此处用 process_start 事件 + detail.etw_events，由 normalize 提升为顶层字段后命中。
    def test_e3_amsi_etw_tamper_via_consumer(self):
        from app.analysis.process_event_consumer import ProcessEventConsumer
        self._ensure_host(3)
        rule = _load_rule("amsi_etw_tamper")
        ProcessEventConsumer.ingest(3, [{
            "event_type": "process_start",
            "pid": 3,
            "ppid": 4,
            "process_name": "x.exe",
            "process_path": "C:\\Temp\\x.exe",
            "start_time": "2026-01-01 00:00:00",
            "detail": {"etw_events": [{"event_type": "amsi", "detail": "memory patch tamper"}]},
        }])
        result = ProcessEventConsumer.evaluate(3, [rule])
        self.assertTrue(result, "amsi_etw_tamper 应命中")
        names = {mr["name"] for ap in result for mr in ap.get("matched_rules", [])}
        self.assertIn("amsi_etw_tamper", names)
        self.assertEqual(result[0]["severity"], "high")

    # ── E4 cross_session_parent_child (medium) ──
    def test_e4_cross_session_parent_child(self):
        from app.rules.rule_engine import RuleEngine
        rule = _load_rule("cross_session_parent_child")
        parent = {"pid": 100, "session": 0}
        child = {"pid": 200, "ppid": 100, "session": 1}
        matches = RuleEngine.evaluate(
            [child], [rule], global_context={"process_map": {100: parent}}
        )
        self._assert_hit(matches, "cross_session_parent_child", "medium")

    # ── E5 injection_window_anomaly (critical) ──
    def test_e5_injection_window_anomaly(self):
        from app.rules.rule_engine import RuleEngine
        rule = _load_rule("injection_window_anomaly")
        start = datetime.now() - timedelta(seconds=1)
        evt = start + timedelta(seconds=0.5)
        proc = {
            "pid": 5,
            "start_time": start.strftime("%Y-%m-%d %H:%M:%S"),
            "remote_thread_events": [
                {"timestamp": evt.strftime("%Y-%m-%d %H:%M:%S")},
            ],
        }
        matches = RuleEngine.evaluate([proc], [rule], global_context={})
        self._assert_hit(matches, "injection_window_anomaly", "critical")

    # ── E6 process_vanished_between_snapshots (high) —— 走 ProcessEventConsumer ──
    def test_e6_process_vanished_via_consumer(self):
        from app.analysis.process_event_consumer import ProcessEventConsumer
        self._ensure_host(6)
        rule = _load_rule("process_vanished_between_snapshots")
        ProcessEventConsumer.ingest(6, [{
            "event_type": "process_start",
            "pid": 6,
            "ppid": 4,
            "process_name": "ghost.exe",
            "process_path": "C:\\Temp\\ghost.exe",
            "start_time": "2026-01-01 00:00:00",
        }])
        # 快照仅含 pid 999（不含 pid 6）→ 归一化项 seen_in_snapshot=False → 命中
        result = ProcessEventConsumer.evaluate(6, [rule], snapshot_processes=[{"pid": 999}])
        self.assertTrue(result, "process_vanished 应命中")
        names = {mr["name"] for ap in result for mr in ap.get("matched_rules", [])}
        self.assertIn("process_vanished_between_snapshots", names)
        self.assertEqual(result[0]["severity"], "high")

    # ── E7 revoked_expired_signature (high) —— 临时改写模块级缓存 ──
    def test_e7_revoked_expired_signature(self):
        import app.rules.rule_engine as re_mod
        from app.rules.rule_engine import RuleEngine
        re_mod._REVOKED_CA_CACHE = {"cn=fake malicious ca"}
        rule = _load_rule("revoked_expired_signature")
        matches = RuleEngine.evaluate(
            [{"pid": 7, "exe_signer": "CN=Fake Malicious CA"}], [rule], global_context={}
        )
        self._assert_hit(matches, "revoked_expired_signature", "high")

    def tearDown(self):
        # E7 临时改写了吊销缓存，必须复位，避免影响其它用例/测试文件
        self._reset_revoked_cache()


class TestP2AgentRevokedFile(DBTestBase):
    """T-P2-2 文件级吊销库加载链路（写入 revoked_ca.json → 重读 → 还原）."""

    def test_revoked_ca_json_load_chain(self):
        import app.rules.rule_engine as re_mod
        from app.rules.rule_engine import RuleEngine

        # 备份原文件内容
        original = REVOKED_CA_PATH.read_text(encoding="utf-8")
        try:
            # 写入模拟吊销库
            REVOKED_CA_PATH.write_text(
                json.dumps({"revoked_signers": ["cn=fake malicious ca"]}, ensure_ascii=False),
                encoding="utf-8",
            )
            # 强制缓存失效，使 _load_revoked_signers 重新读取文件
            re_mod._REVOKED_CA_CACHE = None

            rule = _load_rule("revoked_expired_signature")
            matches = RuleEngine.evaluate(
                [{"pid": 7, "exe_signer": "CN=Fake Malicious CA"}], [rule], global_context={}
            )
            hit = next(
                (m for m in matches if m["rule_name"] == "revoked_expired_signature"), None
            )
            self.assertIsNotNone(hit, "文件级吊销库命中后 revoked_expired_signature 应命中")
            self.assertEqual(hit["severity"], "high")
        finally:
            # 还原文件 + 复位缓存，保证不改变仓库状态
            REVOKED_CA_PATH.write_text(original, encoding="utf-8")
            re_mod._REVOKED_CA_CACHE = None


class TestP2AgentEndpoint(DBTestBase):
    """T-P2-3 端点 POST /api/hosts/{host_id}/process-events（薄封装落库→消费打通）."""

    def test_process_events_endpoint_ingest_and_consume(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.analysis.process_event_consumer import ProcessEventConsumer
        from app.api import process_events

        # 仅挂载该 router 的最小 FastAPI，避免拉起整个 app
        app = FastAPI()
        app.include_router(process_events.router, prefix="/api", tags=["进程事件"])
        client = TestClient(app)

        host_id = 10
        self._ensure_host(host_id)

        events = [
            {
                "event_type": "process_start", "pid": 50, "ppid": 4,
                "process_name": "x.exe", "process_path": "C:\\Temp\\x.exe",
                "start_time": "2026-01-01 00:00:00",
                "detail": {"memory_sections": [{"pe_in_memory": True}]},
            },
            {
                "event_type": "process_start", "pid": 51, "ppid": 4,
                "process_name": "y.exe", "process_path": "C:\\Temp\\y.exe",
                "start_time": "2026-01-01 00:00:00",
            },
        ]
        resp = client.post(f"/api/hosts/{host_id}/process-events", json=events)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get("written"), 2)

        # 证明端点真正打通落库→消费链：normalize 能查出这些事件
        normalized = ProcessEventConsumer.normalize(host_id)
        pids = {p["pid"] for p in normalized}
        self.assertEqual(pids, {50, 51})
        # detail 中的高级字段被正确提升为顶层
        mem_proc = next(p for p in normalized if p["pid"] == 50)
        self.assertEqual(mem_proc.get("memory_sections"), [{"pe_in_memory": True}])


class TestP2AgentReverse(DBTestBase):
    """T-P2-1 反向用例：R1-R7（缺字段返回空 / 不崩）."""

    def _assert_no_hit(self, matches, rule_name):
        for m in matches:
            self.assertNotEqual(m["rule_name"], rule_name, f"规则 {rule_name} 反向不应命中")

    # ── R1 缺 memory_sections → fileless 不命中 ──
    def test_r1_no_memory_sections(self):
        from app.rules.rule_engine import RuleEngine
        rule = _load_rule("fileless_reflective_injection")
        matches = RuleEngine.evaluate([{"pid": 1, "name": "x.exe"}], [rule], global_context={})
        self.assertEqual(matches, [])
        self._assert_no_hit(matches, "fileless_reflective_injection")

    # ── R2 无 etw_events → amsi_etw_tamper 不命中 ──
    def test_r2_no_etw_events(self):
        from app.rules.rule_engine import RuleEngine
        rule = _load_rule("amsi_etw_tamper")
        matches = RuleEngine.evaluate([{"pid": 3, "name": "x.exe"}], [rule], global_context={})
        self.assertEqual(matches, [])

    # ── R3 无 session → cross_session 不命中 ──
    def test_r3_no_session(self):
        from app.rules.rule_engine import RuleEngine
        rule = _load_rule("cross_session_parent_child")
        matches = RuleEngine.evaluate(
            [{"pid": 200, "ppid": 100}], [rule], global_context={"process_map": {}}
        )
        self.assertEqual(matches, [])

    # ── R4 无 remote_thread → injection_window 不命中 ──
    def test_r4_no_remote_thread(self):
        from app.rules.rule_engine import RuleEngine
        rule = _load_rule("injection_window_anomaly")
        matches = RuleEngine.evaluate(
            [{"pid": 5, "start_time": "2026-01-01 00:00:00"}], [rule], global_context={}
        )
        self.assertEqual(matches, [])

    # ── R5 空吊销库 → revoked 不命中 ──
    def test_r5_empty_revoked_store(self):
        import app.rules.rule_engine as re_mod
        from app.rules.rule_engine import RuleEngine
        re_mod._REVOKED_CA_CACHE = None  # 强制从空文件重读
        rule = _load_rule("revoked_expired_signature")
        matches = RuleEngine.evaluate(
            [{"pid": 7, "exe_signer": "CN=Some Legit CA"}], [rule], global_context={}
        )
        self.assertEqual(matches, [])
        self._reset_revoked_cache()

    # ── R6 老 Agent 无新字段跑全流程（consumer）→ 不崩、不误报 ──
    def test_r6_legacy_agent_full_pipeline_no_false_positive(self):
        from app.analysis.process_event_consumer import ProcessEventConsumer
        self._ensure_host(6)
        ProcessEventConsumer.ingest(6, [{
            "event_type": "process_start",
            "pid": 77,
            "ppid": 4,
            "process_name": "notepad.exe",
            "process_path": "C:\\Windows\\System32\\notepad.exe",
            "start_time": "2026-01-01 00:00:00",
        }])
        # 快照含该 pid → seen_in_snapshot=True，vanished 不误报；其余规则无高级字段也不命中
        result = ProcessEventConsumer.evaluate(6, _load_p2_rules(), snapshot_processes=[{"pid": 77}])
        self.assertEqual(result, [])

    # ── R7 不存在主机 evaluate 返回空、不崩 ──
    def test_r7_consumer_evaluate_unknown_host(self):
        from app.analysis.process_event_consumer import ProcessEventConsumer
        result = ProcessEventConsumer.evaluate(999, _load_p2_rules())
        self.assertEqual(result, [])


class TestP2AgentSnapshotModeA(DBTestBase):
    """T-P2-4 快照双模集成验证：Mode A（快照增强）即激活 P2，无需事件管线."""

    def test_snapshot_mode_a_activates_p2(self):
        from app.analysis.anomaly_detector import AnomalyDetector

        rules = _load_p2_rules()
        raw_data = {
            "processes": [
                {
                    "pid": 100,
                    "name": "services.exe",
                    "path": "C:\\Windows\\System32\\services.exe",
                    "ppid": 4,
                    "session": 0,
                },
                {
                    # 跨会话子进程（session 1，父 session 0）+ 内存注入痕迹
                    "pid": 200,
                    "name": "powershell.exe",
                    "path": "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe",
                    "ppid": 100,
                    "session": 1,
                    "memory_sections": [{"injection": True}],
                },
                {
                    # 脚本解释器内存加载异常 PE
                    "pid": 300,
                    "name": "powershell.exe",
                    "path": "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe",
                    "ppid": 4,
                    "memory_sections": [{"pe_in_memory": True}],
                },
            ]
        }
        abnormal = AnomalyDetector.detect_processes(raw_data, rules)
        self.assertTrue(abnormal, "快照 Mode A 应激活 P2 并检出异常进程")

        names = set()
        for ap in abnormal:
            for mr in ap.get("matched_rules", []):
                names.add(mr["name"])

        self.assertIn("fileless_reflective_injection", names)
        self.assertIn("script_interpreter_memory_pe", names)
        self.assertIn("cross_session_parent_child", names)


if __name__ == "__main__":
    unittest.main()
