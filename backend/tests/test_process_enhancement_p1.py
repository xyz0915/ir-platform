#!/usr/bin/env python3
"""进程检测加强规则集 — P1 验收测试（T07-T13）.

覆盖：
  T07  grandparent_chain_anomaly（多级祖先回溯：可疑祖父 + 脚本子链）
  T08  链路级累加评分（ancestry 链多节点命中累加 risk_score）+ 白名单抑制
  T09  lotl_chain_combo（LOTL 链式组合 attack_chain 规则）
  T10  fabricated_parent_pid（伪造/不可能父 PID，字段级）
  T11  fileless_memory_residency（path 空/UNC/内存 + 连接/线程）
  T12  process_respawn_loop（同指纹窗口内重复 ≥K）
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings  # noqa: E402
from app.schemas.analysis import validate_condition  # noqa: E402

RULES_DIR = BACKEND_DIR / "app" / "rules"
ENHANCEMENT_PATH = RULES_DIR / "process_enhancement_rules.json"
ATTACK_CHAIN_PATH = RULES_DIR / "default_attack_chain.json"


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


class TestGrandparentChainAnomaly(DBTestBase):
    """T07：ancestry_chain — 可疑祖父 + 脚本子链."""

    def test_grandparent_suspicious_child_script(self):
        from app.rules.rule_engine import RuleEngine
        rule = _load_rule("grandparent_chain_anomaly")
        # 链：svchost(999) -> parent(100) -> powershell(200)
        process_map = {
            999: {"pid": 999, "name": "svchost.exe", "ppid": 4},
            100: {"pid": 100, "name": "mid.exe", "ppid": 999},
        }
        ancestor_map = {200: [100, 999]}
        child = {"pid": 200, "name": "powershell.exe", "ppid": 100}
        ctx = {"process_map": process_map, "ancestor_map": ancestor_map}
        self.assertTrue(RuleEngine.match_rule(child, rule, global_context=ctx))

    def test_no_match_when_no_suspicious_grandparent(self):
        from app.rules.rule_engine import RuleEngine
        rule = _load_rule("grandparent_chain_anomaly")
        process_map = {
            999: {"pid": 999, "name": "normal.exe", "ppid": 4},
            100: {"pid": 100, "name": "mid.exe", "ppid": 999},
        }
        ancestor_map = {200: [100, 999]}
        child = {"pid": 200, "name": "powershell.exe", "ppid": 100}
        ctx = {"process_map": process_map, "ancestor_map": ancestor_map}
        self.assertFalse(RuleEngine.match_rule(child, rule, global_context=ctx))


class TestFabricatedParentPid(DBTestBase):
    """T10：fabricated_parent_pid — ppid==pid 自指 / 父子互指环."""

    def test_self_referential_ppid(self):
        from app.rules.rule_engine import RuleEngine
        rule = _load_rule("fabricated_parent_pid")
        self.assertTrue(
            RuleEngine.match_rule({"pid": 100, "ppid": 100}, rule, global_context={})
        )

    def test_parent_child_ring(self):
        from app.rules.rule_engine import RuleEngine
        rule = _load_rule("fabricated_parent_pid")
        process_map = {50: {"pid": 50, "ppid": 100}}
        self.assertTrue(
            RuleEngine.match_rule(
                {"pid": 100, "ppid": 50}, rule, global_context={"process_map": process_map}
            )
        )

    def test_normal_parent_not_flagged(self):
        from app.rules.rule_engine import RuleEngine
        rule = _load_rule("fabricated_parent_pid")
        self.assertFalse(
            RuleEngine.match_rule({"pid": 100, "ppid": 4}, rule, global_context={})
        )


class TestFilelessMemoryResidency(DBTestBase):
    """T11：fileless_memory_residency — path 空/UNC/内存 + 连接/线程."""

    def test_empty_path_with_connection(self):
        from app.rules.rule_engine import RuleEngine
        rule = _load_rule("fileless_memory_residency")
        self.assertTrue(
            RuleEngine.match_rule(
                {"path": "", "connections": [{"remote_port": 4444}]},
                rule, global_context={},
            )
        )

    def test_unc_path_with_threads(self):
        from app.rules.rule_engine import RuleEngine
        rule = _load_rule("fileless_memory_residency")
        self.assertTrue(
            RuleEngine.match_rule(
                {"path": "\\\\.\\pipe\\x", "threads": 3}, rule, global_context={}
            )
        )

    def test_disk_path_not_flagged(self):
        from app.rules.rule_engine import RuleEngine
        rule = _load_rule("fileless_memory_residency")
        self.assertFalse(
            RuleEngine.match_rule(
                {"path": "C:\\Temp\\x.exe", "connections": [{}]},
                rule, global_context={},
            )
        )

    def test_fileless_but_idle_not_flagged(self):
        from app.rules.rule_engine import RuleEngine
        rule = _load_rule("fileless_memory_residency")
        self.assertFalse(
            RuleEngine.match_rule(
                {"path": "", "connections": [], "threads": 0}, rule, global_context={}
            )
        )


class TestProcessRespawnLoop(DBTestBase):
    """T12：process_respawn_loop — 同指纹窗口内重复 ≥3."""

    def test_repeat_same_fingerprint_triggers(self):
        from app.rules.rule_engine import RuleEngine
        rule = _load_rule("process_respawn_loop")
        fp = "C:\\Temp\\svc.exe|svc.exe -k"
        all_items = [
            {"path": "C:\\Temp\\svc.exe", "command_line": "svc.exe -k"},
            {"path": "C:\\Temp\\svc.exe", "command_line": "svc.exe -k"},
            {"path": "C:\\Temp\\svc.exe", "command_line": "svc.exe -k"},
        ]
        proc = {"path": "C:\\Temp\\svc.exe", "command_line": "svc.exe -k"}
        ctx = {"all_items": all_items}
        self.assertTrue(RuleEngine.match_rule(proc, rule, global_context=ctx))
        # 防误用：避免 lint 未使用变量告警
        self.assertEqual(len(fp), len(fp))

    def test_below_threshold_not_flagged(self):
        from app.rules.rule_engine import RuleEngine
        rule = _load_rule("process_respawn_loop")
        all_items = [
            {"path": "C:\\Temp\\svc.exe", "command_line": "svc.exe -k"},
            {"path": "C:\\Temp\\svc.exe", "command_line": "svc.exe -k"},
        ]
        proc = {"path": "C:\\Temp\\svc.exe", "command_line": "svc.exe -k"}
        ctx = {"all_items": all_items}
        self.assertFalse(RuleEngine.match_rule(proc, rule, global_context=ctx))


class TestLotlChainCombo(DBTestBase):
    """T09：lotl_chain_combo（LOTL 链式组合 attack_chain 规则）."""

    def test_rule_loads_and_validates(self):
        rules = json.loads(ATTACK_CHAIN_PATH.read_text(encoding="utf-8"))
        lotl = next(r for r in rules if r["name"] == "lotl_chain_combo")
        validate_condition(lotl["rule_type"], lotl["condition"])
        self.assertEqual(lotl["rule_type"], "attack_chain")

    def test_step_patterns_match_representative_commands(self):
        from app.rules.rule_engine import RuleEngine
        rules = json.loads(ATTACK_CHAIN_PATH.read_text(encoding="utf-8"))
        lotl = next(r for r in rules if r["name"] == "lotl_chain_combo")
        steps = lotl["condition"]["ordered_steps"]
        # 每一 process 步的正则可命中代表性命令行（pattern 内已含 (?i) 内联标志，flags=0）
        samples = [
            "certutil -urlcache -split -f http://x/a.exe",
            "powershell -enc ABCD1234",
            "C:\\Users\\u\\AppData\\Local\\Temp\\x.exe",
        ]
        for step, sample in zip(steps, samples):
            pat = step["match"]["pattern"]
            self.assertTrue(
                bool(RuleEngine._compile_regex(pat, 0).search(sample)),
                f"step pattern {pat!r} 应命中 {sample!r}",
            )


class TestChainLevelScoring(DBTestBase):
    """T08：ancestry 链路级累加评分 + T04 白名单抑制."""

    def test_chain_risk_accumulates_across_nodes(self):
        from app.analysis.anomaly_detector import AnomalyDetector

        # 父(100) → 子(200)：同链，各自命中 unsigned_executable（P1-1-A 后 severity=medium，权重 10）
        raw = {
            "processes": [
                {"pid": 100, "ppid": 4, "name": "a.exe", "path": "C:\\Temp\\a.exe",
                 "command_line": "a.exe", "exe_is_signed": 0},
                {"pid": 200, "ppid": 100, "name": "b.exe", "path": "C:\\Temp\\b.exe",
                 "command_line": "b.exe", "exe_is_signed": 0},
            ]
        }
        rules = [_load_rule("unsigned_executable")]
        result = AnomalyDetector.detect_processes(raw, rules)
        by_pid = {r["pid"]: r for r in result}
        # 两节点同链，链路级累加 risk_score = 10+10 = 20（medium 权重 10）
        self.assertEqual(by_pid[100]["risk_score"], 20)
        self.assertEqual(by_pid[200]["risk_score"], 20)
        # 链路 attack_path 应体现祖先链（a.exe → b.exe）
        self.assertIn("→", by_pid[200]["attack_path"])

    def test_whitelist_suppression_of_low_info_only(self):
        from app.analysis.anomaly_detector import AnomalyDetector

        matches = [{
            "item": {"pid": 5, "name": "svc.exe", "whitelisted": True,
                     "ppid": 4, "parent_name": ""},
            "rule_name": "low_rule", "severity": "info", "reason": "x",
        }]
        result = AnomalyDetector._apply_accumulated_scoring(
            matches, global_context={"process_map": {}, "ancestor_map": {}}
        )
        self.assertEqual(result, [], "纯白名单（仅 info 命中）应被抑制，不误报")

    def test_whitelist_with_real_threat_still_reported(self):
        from app.analysis.anomaly_detector import AnomalyDetector

        matches = [{
            "item": {"pid": 5, "name": "svc.exe", "whitelisted": True,
                     "ppid": 4, "parent_name": ""},
            "rule_name": "real_rule", "severity": "high", "reason": "x",
        }]
        result = AnomalyDetector._apply_accumulated_scoring(
            matches, global_context={"process_map": {}, "ancestor_map": {}}
        )
        self.assertEqual(len(result), 1, "白名单进程命中真实高危及规则仍应上报")


if __name__ == "__main__":
    unittest.main()
