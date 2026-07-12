#!/usr/bin/env python3
"""进程树与异常进程检测增强 — 单元测试（T1-T8 验收）.

覆盖：
  1. 5 个新 behavior pattern 命中（zombie_process / process_name_spoof /
     suspicious_path / hidden_process / anomalous_net_process）
  2. orphan_process 修正（Windows ppid=4 不误报、父不存在命中、ppid=0/1 不误报）
  3. suspicious_parent 扩展（condition 驱动 + 默认含 office/浏览器/PDF/压缩/IM 父）
  4. SEVERITY 权重统一后 RiskAssessor 累加正确性
  5. §3.8 severity 提升后 abnormal_processes.severity 取值正确
  6. seed 机制：seed_rules_process.json 可正确入库并被 load_rules 读到
"""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

# ── 项目路径准备 ────────────────────────────────────────────────────────
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

DOCS_DIR = BACKEND_DIR.parent / "docs"
DEFAULT_RULES_PATH = BACKEND_DIR / "app" / "rules" / "default_rules.json"
SEED_PROCESS_PATH = DOCS_DIR / "seed_rules_process.json"

from app.config import settings  # noqa: E402

UNIFIED_WEIGHTS = {"critical": 35, "high": 20, "medium": 10, "low": 5, "info": 1}


class DBTestBase(unittest.TestCase):
    """共用：初始化临时 SQLite 数据库."""

    @classmethod
    def setUpClass(cls):
        cls.db_path = tempfile.mktemp(suffix=".db")
        settings.DB_PATH = cls.db_path
        # 同时指向临时库（get_connection 读取 settings.DB_PATH）
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


def _behavior_rule(name: str, pattern: str, **extra) -> dict:
    """构造一条 behavior 规则 dict（供 match_rule 直接调用）."""
    condition = {"pattern": pattern, "description": f"test {pattern}"}
    condition.update(extra)
    return {
        "name": name,
        "rule_type": "behavior",
        "severity": "high",
        "category": "behavior",
        "condition": condition,
    }


class TestNewBehaviorPatterns(DBTestBase):
    """T1/T2：5 个新 behavior pattern 命中验证."""

    def test_process_name_spoof_hits(self):
        from app.rules.rule_engine import RuleEngine

        rule = _behavior_rule("process_name_spoof", "process_name_spoof")
        # 双扩展名（良性文档叠加 exe）
        self.assertTrue(RuleEngine.match_rule({"name": "invoice.jpg.exe"}, rule))
        # 可执行叠加可执行
        self.assertTrue(RuleEngine.match_rule({"name": "svchost.exe.exe"}, rule))
        # 大小写混淆
        self.assertTrue(RuleEngine.match_rule({"name": "PowerShell.exe"}, rule))
        # 相似名（编辑距离==1）
        self.assertTrue(RuleEngine.match_rule({"name": "svch0st.exe"}, rule))
        self.assertTrue(RuleEngine.match_rule({"name": "cxmd.exe"}, rule))
        # Unicode 同形（全角）
        self.assertTrue(RuleEngine.match_rule({"name": "ｓｖｃｈｏｓｔ.exe"}, rule))

    def test_process_name_spoof_misses(self):
        from app.rules.rule_engine import RuleEngine

        rule = _behavior_rule("process_name_spoof", "process_name_spoof")
        # 合法系统进程（精确同名，无伪装）
        self.assertFalse(RuleEngine.match_rule({"name": "svchost.exe"}, rule))
        # 普通进程
        self.assertFalse(RuleEngine.match_rule({"name": "notepad.exe"}, rule))
        # 文档文件（非双扩展名 exe）
        self.assertFalse(RuleEngine.match_rule({"name": "report.pdf"}, rule))

    def test_suspicious_path_hits(self):
        from app.rules.rule_engine import RuleEngine

        rule = _behavior_rule("suspicious_process_path", "suspicious_path")
        cases = [
            "C:\\Temp\\evil.exe",                 # 临时目录
            "C:\\Users\\user\\Downloads\\x.exe",  # 下载目录
            "D:\\Windows\\System32\\evil.exe",     # 盘符仿冒 system32
            "C:\\Windows\\system32.exe\\evil.exe",  # system32.exe 伪装
            "C:\\Users\\user\\evil.exe",          # 用户目录 exe
            "C:\\test\\file.txt:stream.exe",       # ADS 备用数据流
            "\\\\server\\share\\x.exe",            # 异常 UNC
        ]
        for path in cases:
            with self.subTest(path=path):
                self.assertTrue(RuleEngine.match_rule({"name": "x.exe", "path": path}, rule))

    def test_suspicious_path_misses(self):
        from app.rules.rule_engine import RuleEngine

        rule = _behavior_rule("suspicious_process_path", "suspicious_path")
        cases = [
            "C:\\Windows\\System32\\svchost.exe",         # 系统目录
            "C:\\Windows\\SysWOW64\\x.dll",                # SysWOW64
            "C:\\Program Files\\App\\app.exe",             # 程序目录白名单
            "C:\\ProgramData\\Vendor.install\\upd.exe",    # 安装器白名单
        ]
        for path in cases:
            with self.subTest(path=path):
                self.assertFalse(RuleEngine.match_rule({"name": "x.exe", "path": path}, rule))

    def test_hidden_process_hits(self):
        from app.rules.rule_engine import RuleEngine

        rule = _behavior_rule("hidden_or_spoofed_service_process", "hidden_process")
        # 退化判定：同名不同路径（仿冒系统服务）
        self.assertTrue(
            RuleEngine.match_rule(
                {"name": "svchost.exe", "path": "C:\\Temp\\svchost.exe"}, rule
            )
        )
        # 增强判定：交互式进程无窗口（数据含 window_title/session）
        self.assertTrue(
            RuleEngine.match_rule(
                {
                    "name": "powershell.exe",
                    "path": "C:\\Windows\\System32\\powershell.exe",
                    "window_title": "",
                    "session": 1,
                },
                rule,
            )
        )

    def test_hidden_process_misses(self):
        from app.rules.rule_engine import RuleEngine

        rule = _behavior_rule("hidden_or_spoofed_service_process", "hidden_process")
        # 系统服务在正确路径
        self.assertFalse(
            RuleEngine.match_rule(
                {"name": "svchost.exe", "path": "C:\\Windows\\System32\\svchost.exe"}, rule
            )
        )
        # 非系统服务名在临时目录
        self.assertFalse(
            RuleEngine.match_rule(
                {"name": "notepad.exe", "path": "C:\\Temp\\notepad.exe"}, rule
            )
        )
        # 有窗口标题（非隐藏）
        self.assertFalse(
            RuleEngine.match_rule(
                {
                    "name": "powershell.exe",
                    "path": "C:\\Windows\\System32\\powershell.exe",
                    "window_title": "PowerShell",
                    "session": 1,
                },
                rule,
            )
        )

    def test_anomalous_net_process_hits(self):
        from app.rules.rule_engine import RuleEngine

        rule = _behavior_rule("anomalous_network_process", "anomalous_net_process")
        # 脚本解释器连接 C2 端口
        self.assertTrue(
            RuleEngine.match_rule(
                {
                    "name": "powershell.exe",
                    "path": "C:\\Temp\\x.exe",
                    "connections": [{"remote_port": 4444}],
                },
                rule,
            )
        )
        # 无签名进程非业务端口外连
        self.assertTrue(
            RuleEngine.match_rule(
                {
                    "name": "weird.exe",
                    "path": "C:\\Temp\\weird.exe",
                    "connections": [{"remote_port": 9000}],
                },
                rule,
            )
        )
        # 经 global_context["connections"] 回退（按 pid 关联）
        self.assertTrue(
            RuleEngine.match_rule(
                {"name": "cmd.exe", "path": "C:\\Temp\\c.exe", "pid": 999},
                rule,
                global_context={
                    "connections": [{"pid": 999, "remote_port": 31337}],
                },
            )
        )

    def test_anomalous_net_process_misses(self):
        from app.rules.rule_engine import RuleEngine

        rule = _behavior_rule("anomalous_network_process", "anomalous_net_process")
        # 浏览器（非脚本解释器）连接业务端口 443，且在系统目录
        self.assertFalse(
            RuleEngine.match_rule(
                {
                    "name": "chrome.exe",
                    "path": "C:\\Windows\\System32\\chrome.exe",
                    "connections": [{"remote_port": 443}],
                },
                rule,
            )
        )
        # 脚本解释器连接业务端口（无外连到可疑端口）
        self.assertFalse(
            RuleEngine.match_rule(
                {
                    "name": "powershell.exe",
                    "path": "C:\\Temp\\x.exe",
                    "connections": [{"remote_port": 443}],
                },
                rule,
            )
        )
        # 无外连
        self.assertFalse(
            RuleEngine.match_rule(
                {"name": "powershell.exe", "path": "C:\\Temp\\x.exe", "connections": []},
                rule,
            )
        )

    def test_zombie_process_hits(self):
        from app.rules.rule_engine import RuleEngine

        rule = _behavior_rule("zombie_process_suspect", "zombie_process", threshold_days=7)
        # 线程数为 0 且启动时间远超阈值（疑似残留句柄）
        self.assertTrue(
            RuleEngine.match_rule(
                {
                    "name": "svchost.exe",
                    "path": "C:\\Windows\\System32\\svchost.exe",
                    "threads": 0,
                    "start_time": "2020-01-01 00:00:00",
                },
                rule,
            )
        )
        # 完全孤立（无外连）且启动时间超阈值
        self.assertTrue(
            RuleEngine.match_rule(
                {
                    "name": "orphan.exe",
                    "path": "C:\\Temp\\orphan.exe",
                    "threads": 5,
                    "start_time": "2020-01-01 00:00:00",
                    "connections": [],
                },
                rule,
            )
        )

    def test_zombie_process_misses(self):
        from app.rules.rule_engine import RuleEngine

        rule = _behavior_rule("zombie_process_suspect", "zombie_process", threshold_days=7)
        # 启动时间较近（未超阈值）
        self.assertFalse(
            RuleEngine.match_rule(
                {"name": "svchost.exe", "threads": 0, "start_time": "2099-01-01 00:00:00"},
                rule,
            )
        )
        # 线程数正常且有外连（非孤立）
        self.assertFalse(
            RuleEngine.match_rule(
                {
                    "name": "svchost.exe",
                    "threads": 4,
                    "start_time": "2020-01-01 00:00:00",
                    "connections": [{"remote_port": 445}],
                },
                rule,
            )
        )


class TestOrphanProcessCorrection(DBTestBase):
    """T2：orphan_process 判定修正."""

    def _ctx(self, pids):
        return {"process_map": {pid: {"pid": pid, "name": f"p{pid}.exe"} for pid in pids}}

    def test_ppid_4_no_false_positive(self):
        from app.rules.rule_engine import RuleEngine

        rule = _behavior_rule("orphan_process", "orphan_process")
        # Windows System(4) 作为父进程 → 不误报
        self.assertFalse(
            RuleEngine.match_rule({"name": "x.exe", "ppid": 4}, rule, global_context=self._ctx([4]))
        )

    def test_ppid_not_in_map_hits(self):
        from app.rules.rule_engine import RuleEngine

        rule = _behavior_rule("orphan_process", "orphan_process")
        # 父 PID 不在进程列表 → 真孤儿命中
        self.assertTrue(
            RuleEngine.match_rule(
                {"name": "x.exe", "ppid": 9999}, rule, global_context=self._ctx([4, 100])
            )
        )

    def test_ppid_0_and_1_not_flagged(self):
        from app.rules.rule_engine import RuleEngine

        rule = _behavior_rule("orphan_process", "orphan_process")
        # ppid=0（System Idle）/ ppid=1（init）排除，避免误报
        self.assertFalse(
            RuleEngine.match_rule({"name": "x.exe", "ppid": 0}, rule, global_context=self._ctx([4]))
        )
        self.assertFalse(
            RuleEngine.match_rule({"name": "x.exe", "ppid": 1}, rule, global_context=self._ctx([4]))
        )
        self.assertFalse(
            RuleEngine.match_rule({"name": "x.exe", "ppid": None}, rule, global_context=self._ctx([4]))
        )

    def test_real_parent_present_not_orphan(self):
        from app.rules.rule_engine import RuleEngine

        rule = _behavior_rule("orphan_process", "orphan_process")
        # 父 PID 在进程列表 → 非孤儿
        self.assertFalse(
            RuleEngine.match_rule(
                {"name": "x.exe", "ppid": 100}, rule, global_context=self._ctx([4, 100])
            )
        )


class TestSuspiciousParentExtension(DBTestBase):
    """T6：suspicious_parent condition 驱动 + 默认扩展父清单."""

    def test_default_expanded_parents(self):
        from app.rules.rule_engine import RuleEngine

        # condition 未配置 parents/children → 回退扩展默认清单
        rule = _behavior_rule("suspicious_parent", "suspicious_parent")
        # 浏览器父 + 脚本子（新增父）
        self.assertTrue(
            RuleEngine.match_rule(
                {"name": "powershell.exe", "parent_name": "chrome.exe"}, rule
            )
        )
        # PDF 阅读器父
        self.assertTrue(
            RuleEngine.match_rule(
                {"name": "cmd.exe", "parent_name": "acrord32.exe"}, rule
            )
        )
        # IM 父
        self.assertTrue(
            RuleEngine.match_rule(
                {"name": "wscript.exe", "parent_name": "wechat.exe"}, rule
            )
        )
        # 原 office 父仍生效
        self.assertTrue(
            RuleEngine.match_rule(
                {"name": "cmd.exe", "parent_name": "winword.exe"}, rule
            )
        )

    def test_condition_driven_parents_children(self):
        from app.rules.rule_engine import RuleEngine

        rule = _behavior_rule(
            "suspicious_parent",
            "suspicious_parent",
            parents=["chrome"],
            children=["python"],
        )
        # 规则自定义父/子清单（大小写/扩展名归一）
        self.assertTrue(
            RuleEngine.match_rule(
                {"name": "python3.exe", "parent_name": "CHROME.EXE"}, rule
            )
        )
        # 不在自定义清单 → 不命中
        self.assertFalse(
            RuleEngine.match_rule(
                {"name": "notepad.exe", "parent_name": "chrome.exe"}, rule
            )
        )

    def test_negative_cases(self):
        from app.rules.rule_engine import RuleEngine

        rule = _behavior_rule("suspicious_parent", "suspicious_parent")
        # explorer 父（非可疑父清单）
        self.assertFalse(
            RuleEngine.match_rule(
                {"name": "powershell.exe", "parent_name": "explorer.exe"}, rule
            )
        )
        # 浏览器父但子非脚本解释器
        self.assertFalse(
            RuleEngine.match_rule(
                {"name": "notepad.exe", "parent_name": "chrome.exe"}, rule
            )
        )


class TestSeverityWeightsUnified(DBTestBase):
    """T4：SEVERITY 权重统一 + RiskAssessor 累加正确性."""

    def test_weights_unified(self):
        from app.analysis.anomaly_detector import SEVERITY_SCORES
        from app.analysis.risk_assessor import RiskAssessor

        self.assertEqual(SEVERITY_SCORES, UNIFIED_WEIGHTS)
        self.assertEqual(RiskAssessor.SEVERITY_WEIGHTS, UNIFIED_WEIGHTS)

    def test_risk_assessor_accumulation(self):
        from app.analysis.risk_assessor import RiskAssessor

        # 单条 high → 20（低于 high 阈值 60）
        res = RiskAssessor.assess({"abnormal_processes": [{"severity": "high"}]})
        self.assertEqual(res["risk_score"], 20)
        self.assertEqual(res["risk_level"], "low")

        # 两条 high → 40 → medium
        res = RiskAssessor.assess(
            {"abnormal_processes": [{"severity": "high"}, {"severity": "high"}]}
        )
        self.assertEqual(res["risk_score"], 40)
        self.assertEqual(res["risk_level"], "medium")

        # 单条 critical（监听后门）→ 35
        res = RiskAssessor.assess({"abnormal_processes": [{"severity": "critical"}]})
        self.assertEqual(res["risk_score"], 35)
        self.assertEqual(res["risk_level"], "low")

        # 两条 critical → 70 → high
        res = RiskAssessor.assess(
            {"abnormal_processes": [{"severity": "critical"}, {"severity": "critical"}]}
        )
        self.assertEqual(res["risk_score"], 70)
        self.assertEqual(res["risk_level"], "high")

    def test_accumulated_scoring_uses_unified_weights(self):
        from app.analysis.anomaly_detector import AnomalyDetector

        matches = [
            {
                "item": {"pid": 1234, "name": "m.exe", "path": "C:\\Temp\\m.exe",
                         "command_line": "m.exe", "ppid": 4, "parent_name": "cmd.exe"},
                "rule_name": "r1", "severity": "high", "reason": "high issue",
            },
            {
                "item": {"pid": 1234, "name": "m.exe", "path": "C:\\Temp\\m.exe",
                         "command_line": "m.exe", "ppid": 4, "parent_name": "cmd.exe"},
                "rule_name": "r2", "severity": "critical", "reason": "critical issue",
            },
        ]
        result = AnomalyDetector._apply_accumulated_scoring(matches)
        self.assertEqual(len(result), 1)
        # high(20) + critical(35) = 55，上限 100
        self.assertEqual(result[0]["risk_score"], 55)
        self.assertEqual(result[0]["severity"], "critical")


class TestSection38SeverityBumps(DBTestBase):
    """T5：§3.8 规则 severity 提升（读 default_rules.json 校验）."""

    def _load_default_rules(self):
        with open(DEFAULT_RULES_PATH, "r", encoding="utf-8") as f:
            return {r["name"]: r for r in json.load(f)}

    def test_section38_severities(self):
        rules = self._load_default_rules()
        expected = {
            "powershell_encoded_command": "high",
            "powershell_bypass_execution": "high",
            "certutil_download": "high",
            "wmic_process_create": "high",
            "rundll32_suspicious": "high",
            "cmd_powershell_chain": "high",
            "nc_netcat_listener": "critical",
            "unsigned_process": "medium",
            # §3.6：孤儿进程规则 severity 提升
            "orphan_process": "high",
        }
        for name, sev in expected.items():
            with self.subTest(rule=name):
                self.assertIn(name, rules, f"{name} 缺失")
                self.assertEqual(rules[name]["severity"], sev, f"{name} severity 应为 {sev}")


class TestPipelineSeverityFlow(DBTestBase):
    """T5：§3.8 severity 提升后 abnormal_processes.severity 取值正确（端到端）."""

    def _rule(self, name, pattern_or_field, severity, rule_type="regex", **cond):
        if rule_type == "regex":
            condition = {"field": "command_line", "pattern": pattern_or_field, "flags": "ignorecase"}
        else:
            condition = {"pattern": pattern_or_field, "description": "d"}
        condition.update(cond)
        return {
            "name": name, "rule_type": rule_type, "severity": severity,
            "category": "process" if rule_type == "regex" else "behavior",
            "condition": condition,
        }

    def test_nc_listener_critical_flows(self):
        from app.analysis.anomaly_detector import AnomalyDetector

        rules = [self._rule("nc_netcat_listener", r"(nc|netcat).*-l.*-p", "critical")]
        raw = {
            "processes": [
                {
                    "pid": 10, "name": "nc.exe",
                    "path": "C:\\Windows\\System32\\nc.exe",
                    "command_line": "nc -l -p 4444", "ppid": 4,
                }
            ]
        }
        result = AnomalyDetector.detect_processes(raw, rules)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["severity"], "critical")
        self.assertEqual(result[0]["process_name"], "nc.exe")

    def test_powershell_encoded_high_flows(self):
        from app.analysis.anomaly_detector import AnomalyDetector

        rules = [self._rule("powershell_encoded_command", r"powershell.*(-enc|-encodedcommand)\s+", "high")]
        raw = {
            "processes": [
                {
                    "pid": 11, "name": "powershell.exe",
                    "path": "C:\\Windows\\System32\\powershell.exe",
                    "command_line": "powershell -enc ABCD1234", "ppid": 4,
                }
            ]
        }
        result = AnomalyDetector.detect_processes(raw, rules)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["severity"], "high")

    def test_new_behavior_rules_pipeline(self):
        from app.analysis.anomaly_detector import AnomalyDetector

        # 直接加载 5 条新 behavior 规则（与 seed JSON 同构）
        with open(SEED_PROCESS_PATH, "r", encoding="utf-8") as f:
            seed_rules = json.load(f)
        rules = [
            {
                "name": r["name"], "rule_type": r["rule_type"],
                "severity": r["severity"], "category": r.get("category", "behavior"),
                "condition": r["condition"],
            }
            for r in seed_rules
        ]
        raw = {
            "processes": [
                # 进程名伪装
                {"pid": 20, "name": "evil.jpg.exe", "path": "C:\\Temp\\evil.jpg.exe",
                 "command_line": "evil.jpg.exe", "ppid": 4},
                # 仿冒服务进程（同名不同路径）
                {"pid": 21, "name": "svchost.exe", "path": "C:\\Temp\\svchost.exe",
                 "command_line": "svchost.exe", "ppid": 4},
                # 异常网络进程
                {"pid": 22, "name": "powershell.exe", "path": "C:\\Temp\\x.exe",
                 "command_line": "powershell.exe", "ppid": 4,
                 "connections": [{"remote_port": 4444}]},
            ],
            "network": {"connections": []},
        }
        result = AnomalyDetector.detect_processes(raw, rules)
        by_name = {r["process_name"]: r for r in result}
        # 每个进程至少命中一条 high 规则
        self.assertIn("evil.jpg.exe", by_name)
        self.assertIn("svchost.exe", by_name)
        self.assertIn("powershell.exe", by_name)
        for name, ab in by_name.items():
            with self.subTest(proc=name):
                self.assertEqual(ab["severity"], "high")


class TestSeedRulesProcess(DBTestBase):
    """T5：seed 机制 — seed_rules_process.json 入库并被 load_rules 读到."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # 动态加载 docs/seed_rules.py
        spec = importlib.util.spec_from_file_location(
            "seed_rules_process_mod", DOCS_DIR / "seed_rules.py"
        )
        cls.seed_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.seed_mod)
        cls.seed_result = cls.seed_mod.seed(str(SEED_PROCESS_PATH))

    def test_seed_valid_and_loaded(self):
        # validate_condition 通过（无异常）= 全部 valid（failed=0）
        self.assertEqual(self.seed_result["failed"], 0)
        # 种子规则已入库（loader 或 seed 机制均可注入，幂等：已存在则 created=0）
        self.assertIn(self.seed_result["created"], (0, 5))

        from app.rules.rule_engine import RuleEngine, BEHAVIOR_PATTERNS

        # 5 条新 pattern 均在引擎白名单中
        for pat in ("zombie_process", "process_name_spoof", "suspicious_path",
                    "hidden_process", "anomalous_net_process"):
            self.assertIn(pat, BEHAVIOR_PATTERNS)

        # 入库后 load_rules 能读到
        loaded = RuleEngine.load_rules()
        loaded_names = {r["name"] for r in loaded}
        for name in ("process_name_spoof", "suspicious_process_path",
                     "hidden_or_spoofed_service_process", "anomalous_network_process",
                     "zombie_process_suspect"):
            with self.subTest(rule=name):
                self.assertIn(name, loaded_names)

    def test_seed_idempotent(self):
        # 再次 seed 应全部 skipped（幂等）
        again = self.seed_mod.seed(str(SEED_PROCESS_PATH))
        self.assertEqual(again["created"], 0)
        self.assertEqual(again["skipped"], 5)
        self.assertEqual(again["failed"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
