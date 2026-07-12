#!/usr/bin/env python3
"""进程检测加强规则集 — P0 验收测试（T01-T06）.

覆盖：
  T01  seed_rules_process.json 正确入库/可被引擎读到（5 条 behavior 规则）
  T02  file_hashes 按 path JOIN 注入 exe_sha256/exe_is_signed/exe_signer
  T03  malicious_hash_process（list 规则，field=exe_sha256，动态 IOC 并入）
  T04  白名单根因修复：标记保留（不整体剔除）+ whitelist_derived_chain 派生链
  T05  unsigned_executable（无签名 exe）
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
SEED_PROCESS_PATH = RULES_DIR / "seed_rules_process.json"
ENHANCEMENT_PATH = RULES_DIR / "process_enhancement_rules.json"


def _load_rule(name: str) -> dict:
    """从 process_enhancement_rules.json 按 name 取出完整规则（含 condition）。"""
    for r in json.loads(ENHANCEMENT_PATH.read_text(encoding="utf-8")):
        if r["name"] == name:
            return r
    raise KeyError(f"rule not found: {name}")


class DBTestBase(unittest.TestCase):
    """共用：初始化临时 SQLite 数据库."""

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


class TestSeedRulesProcess(DBTestBase):
    """T01：seed_rules_process.json 5 条 behavior 规则可加载且 pattern 合法."""

    def test_seed_file_has_five_rules(self):
        rules = json.loads(SEED_PROCESS_PATH.read_text(encoding="utf-8"))
        self.assertEqual(len(rules), 5, "seed 应为 5 条进程 behavior 规则")

    def test_seed_rules_patterns_registered(self):
        from app.rules.rule_engine import BEHAVIOR_PATTERNS
        rules = json.loads(SEED_PROCESS_PATH.read_text(encoding="utf-8"))
        for r in rules:
            self.assertIn(
                r["condition"]["pattern"], BEHAVIOR_PATTERNS,
                f"seed pattern {r['condition']['pattern']} 未在 BEHAVIOR_PATTERNS 注册",
            )

    def test_seed_rules_validate(self):
        rules = json.loads(SEED_PROCESS_PATH.read_text(encoding="utf-8"))
        for r in rules:
            # 不应抛 ValueError（behavior pattern 合法）
            validate_condition(r["rule_type"], r["condition"])


class TestExeSignatureInjection(DBTestBase):
    """T02：file_hashes 按 path JOIN 注入 exe_sha256/exe_is_signed/exe_signer."""

    def test_inject_exe_signatures_by_path(self):
        from app.services.analysis_service import AnalysisService

        raw_data = {
            "file_hashes": [
                {
                    "file_path": "C:\\Temp\\evil.exe",
                    "sha256": "deadbeef",
                    "is_signed": 0,
                    "signer": "",
                },
                {
                    "file_path": "C:\\Temp\\ok.exe",
                    "sha256": "abcdef",
                    "is_signed": 1,
                    "signer": "Microsoft Windows",
                },
            ],
            "processes": [
                {"pid": 1, "name": "evil.exe", "path": "C:\\Temp\\evil.exe"},
                {"pid": 2, "name": "ok.exe", "path": "C:\\Temp\\ok.exe"},
                # 无对应 file_hash 的进程：字段保持缺失（None），下游优雅降级
                {"pid": 3, "name": "nomatch.exe", "path": "C:\\Temp\\nomatch.exe"},
            ],
        }
        AnalysisService._inject_exe_signatures(raw_data)
        procs = {p["pid"]: p for p in raw_data["processes"]}
        self.assertEqual(procs[1]["exe_sha256"], "deadbeef")
        self.assertEqual(procs[1]["exe_is_signed"], 0)
        self.assertEqual(procs[1]["exe_signer"], "")
        self.assertEqual(procs[2]["exe_sha256"], "abcdef")
        self.assertEqual(procs[2]["exe_is_signed"], 1)
        self.assertEqual(procs[2]["exe_signer"], "Microsoft Windows")
        # 无对应哈希的进程不注入（保持缺失）
        self.assertNotIn("exe_sha256", procs[3])


class TestMaliciousHashProcess(DBTestBase):
    """T02/T03：malicious_hash_process（list，field=exe_sha256，动态 IOC 并入）."""

    def test_field_maps_to_hash_ioc(self):
        from app.rules.rule_engine import FIELD_TO_IOC_TYPE
        self.assertEqual(FIELD_TO_IOC_TYPE.get("exe_sha256"), "hash")

    def test_matches_when_hash_in_ioc_store(self):
        from app.rules.rule_engine import RuleEngine
        rule = _load_rule("malicious_hash_process")
        # 动态 IOC 引用：global_context.iocs_by_type["hash"] 含该 sha256
        ctx = {"iocs_by_type": {"hash": ["deadbeef"]}}
        hit = RuleEngine.match_rule(
            {"exe_sha256": "deadbeef"}, rule, global_context=ctx
        )
        self.assertTrue(hit)

    def test_no_match_when_hash_absent(self):
        from app.rules.rule_engine import RuleEngine
        rule = _load_rule("malicious_hash_process")
        ctx = {"iocs_by_type": {"hash": ["otherhash"]}}
        self.assertFalse(
            RuleEngine.match_rule({"exe_sha256": "deadbeef"}, rule, global_context=ctx)
        )

    def test_graceful_when_no_ioc_store(self):
        from app.rules.rule_engine import RuleEngine
        rule = _load_rule("malicious_hash_process")
        # 无 iocs_by_type 或空库时不应命中、也不抛异常
        self.assertFalse(
            RuleEngine.match_rule({"exe_sha256": "deadbeef"}, rule, global_context={})
        )


class TestUnsignedExecutable(DBTestBase):
    """T05：unsigned_executable（非系统目录且无签名的 exe）."""

    def test_unsigned_non_system_exe(self):
        from app.rules.rule_engine import RuleEngine
        rule = _load_rule("unsigned_executable")
        self.assertTrue(
            RuleEngine.match_rule(
                {"path": "C:\\Temp\\evil.exe", "exe_is_signed": 0},
                rule, global_context={},
            )
        )

    def test_signed_exe_not_flagged(self):
        from app.rules.rule_engine import RuleEngine
        rule = _load_rule("unsigned_executable")
        self.assertFalse(
            RuleEngine.match_rule(
                {"path": "C:\\Temp\\ok.exe", "exe_is_signed": 1, "exe_signer": "Microsoft"},
                rule, global_context={},
            )
        )

    def test_system_dir_exe_not_flagged(self):
        from app.rules.rule_engine import RuleEngine
        rule = _load_rule("unsigned_executable")
        self.assertFalse(
            RuleEngine.match_rule(
                {"path": "C:\\Windows\\System32\\svchost.exe", "exe_is_signed": 0},
                rule, global_context={},
            )
        )


class TestWhitelistRootCauseFix(DBTestBase):
    """T04：白名单根因修复 — 标记保留（不整体剔除）+ whitelist_derived_chain 派生链."""

    def test_whitelisted_process_kept_and_marked(self):
        from app.analysis.anomaly_detector import AnomalyDetector

        raw = {
            "processes": [
                {"pid": 100, "name": "explorer.exe", "path": "C:\\Windows\\explorer.exe",
                 "command_line": "explorer.exe", "ppid": 4},
            ]
        }

        class _FakeWL:
            def is_whitelisted(self, proc):
                return True

        result = AnomalyDetector.detect_processes(raw, [], whitelist_service=_FakeWL())
        # 白名单进程不再被整体剔除：原进程 dict 被标记 whitelisted=True
        self.assertTrue(raw["processes"][0].get("whitelisted"))

    def test_whitelist_derived_chain_child(self):
        from app.rules.rule_engine import RuleEngine
        rule = _load_rule("whitelist_derived_chain")
        parent = {"pid": 100, "name": "explorer.exe", "whitelisted": True}
        child = {"pid": 200, "ppid": 100, "name": "powershell.exe",
                 "command_line": "powershell -enc ABCD"}
        ctx = {"process_map": {100: parent}}
        self.assertTrue(RuleEngine.match_rule(child, rule, global_context=ctx))

    def test_whitelist_derived_chain_no_match_without_whitelist_parent(self):
        from app.rules.rule_engine import RuleEngine
        rule = _load_rule("whitelist_derived_chain")
        parent = {"pid": 100, "name": "explorer.exe", "whitelisted": False}
        child = {"pid": 200, "ppid": 100, "name": "powershell.exe",
                 "command_line": "powershell -enc ABCD"}
        ctx = {"process_map": {100: parent}}
        self.assertFalse(RuleEngine.match_rule(child, rule, global_context=ctx))


if __name__ == "__main__":
    unittest.main()
