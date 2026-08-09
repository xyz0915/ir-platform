"""P2 阶段验收测试 —— 误报治理与工程可观测性.

覆盖 docs/rule-audit/p2/01-design.md §4 的 AC-P2-1 ~ AC-P2-15：

  P2-1 C2 端口 SSOT      : AC-P2-1 ~ AC-P2-5
  P2-2 严重度校准        : AC-P2-6 ~ AC-P2-8
  P2-3 装载可观测性      : AC-P2-9 ~ AC-P2-12
  P2-4 双管道对齐        : AC-P2-13 ~ AC-P2-14

所有用例均不写生产库；涉及文件的用例使用临时目录或改名后还原。
"""

import collections
import json
import logging
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.rules import loader
from app.rules.loader import (
    DATA_FILES,
    load_default_rules,
    load_default_rules_with_report,
)

RULES_DIR = Path(__file__).resolve().parent.parent / "app" / "rules"
C2_PORTS_FILE = RULES_DIR / "c2_ports.json"

# P2 前的两套割裂清单（用于回归证明"漏判已消除"）
LEGACY_ENGINE_PORTS = {4444, 8443, 1337, 31337, 6667, 9999, 1080, 5900}
LEGACY_JSON_PORTS = {4444, 6667, 1337, 4443, 5555, 8888}

CRITICAL_HITL_RULES = {
    "lsass_dump_detection",
    "dcsync_detection",
    "evt_4662_dcsync_suspect",
    "ransomware_behavior_pattern",
    "dpapi_credential_theft",
    "browser_credential_theft",
    "attack_chain_rdp_psexec_lsass",
    "attack_chain_zerologon_dcsync",
    "credential_dump_behavior",
}


def _behavior_rule(name: str, pattern: str, **extra) -> dict:
    condition = {"pattern": pattern, "description": f"test {pattern}"}
    condition.update(extra)
    return {
        "name": name,
        "rule_type": "behavior",
        "severity": "high",
        "category": "behavior",
        "condition": condition,
    }


# ══════════════════════════════════════════════════════════════════
# P2-1 C2 端口单一事实来源
# ══════════════════════════════════════════════════════════════════

class TestP2C2PortSSOT(unittest.TestCase):
    """AC-P2-1 ~ AC-P2-5."""

    def setUp(self):
        from app.rules import rule_engine
        rule_engine._refresh_c2_ports()

    def test_ac_p2_1_ssot_file_covers_union(self):
        """AC-P2-1：c2_ports.json 端口全集 = 原引擎 8 端口 ∪ 原 JSON 6 端口 = 11 个."""
        self.assertTrue(C2_PORTS_FILE.exists(), "c2_ports.json 必须存在")
        cfg = json.loads(C2_PORTS_FILE.read_text(encoding="utf-8"))
        high = set(cfg["high_confidence"]["ports"])
        low = set(cfg["low_confidence"]["ports"])

        self.assertEqual(high & low, set(), "高低置信端口不应重叠")

        union = high | low
        expected = LEGACY_ENGINE_PORTS | LEGACY_JSON_PORTS
        self.assertEqual(union, expected)
        self.assertEqual(len(union), 11)

    def test_ac_p2_2_engine_matches_ssot(self):
        """AC-P2-2：引擎 _C2_PORTS 与 SSOT 文件完全一致."""
        from app.rules.rule_engine import _C2_PORTS, _load_c2_ports

        cfg = json.loads(C2_PORTS_FILE.read_text(encoding="utf-8"))
        expected = set(cfg["high_confidence"]["ports"]) | set(
            cfg["low_confidence"]["ports"])

        self.assertEqual(set(_C2_PORTS), expected)
        layered = _load_c2_ports()
        self.assertEqual(layered["high"], set(cfg["high_confidence"]["ports"]))
        self.assertEqual(layered["low"], set(cfg["low_confidence"]["ports"]))
        self.assertEqual(layered["all"], expected)

    def test_ac_p2_2b_c2_ports_supports_set_ops(self):
        """AC-P2-2 附加：_C2_PORTS 必须是真实集合，支持全部集合运算.

        回归防线：曾考虑用继承 frozenset 的惰性视图实现，会导致 & / - / |
        运算返回空集而静默破坏调用方。
        """
        from app.rules.rule_engine import _C2_PORTS, _BUSINESS_PORTS

        self.assertIsInstance(_C2_PORTS, frozenset)
        self.assertEqual(_C2_PORTS & _BUSINESS_PORTS, frozenset())
        self.assertEqual(len(_C2_PORTS | {80}), len(_C2_PORTS) + 1)
        self.assertIn(4444, _C2_PORTS)
        self.assertNotIn(443, _C2_PORTS)

    def test_ac_p2_3_legacy_rules_replaced(self):
        """AC-P2-3：旧 6 条 c2_port_* 已下线，新 2 条分层规则装载正确."""
        rules = load_default_rules()
        names = {r["name"] for r in rules}

        for legacy in ("c2_port_4444", "c2_port_6667", "c2_port_1337",
                       "c2_port_4443", "c2_port_5555", "c2_port_8888"):
            self.assertNotIn(legacy, names, f"旧规则 {legacy} 应已下线")

        by_name = {r["name"]: r for r in rules}
        self.assertIn("c2_suspicious_port_high", by_name)
        self.assertIn("c2_suspicious_port_low", by_name)

        hi = by_name["c2_suspicious_port_high"]
        lo = by_name["c2_suspicious_port_low"]
        self.assertEqual(hi["severity"], "high")
        self.assertEqual(lo["severity"], "medium",
                         "低置信端口须为 medium，避免 SOCKS/VNC 合法用途误报")

        cfg = json.loads(C2_PORTS_FILE.read_text(encoding="utf-8"))
        self.assertEqual(set(hi["condition"]["values"]),
                         set(cfg["high_confidence"]["ports"]))
        self.assertEqual(set(lo["condition"]["values"]),
                         set(cfg["low_confidence"]["ports"]))

        # 历史可追溯性：旧规则名须登记在 supersedes 中
        self.assertEqual(
            set(hi["condition"]["_meta"]["supersedes"]),
            {"c2_port_4444", "c2_port_6667", "c2_port_1337",
             "c2_port_4443", "c2_port_5555", "c2_port_8888"},
        )

    def test_ac_p2_4_graceful_degradation_when_file_missing(self):
        """AC-P2-4：SSOT 文件缺失时回落内置默认值，不抛异常、能力不归零."""
        from app.rules import rule_engine

        backup = C2_PORTS_FILE.with_suffix(".json.bak")
        shutil.move(str(C2_PORTS_FILE), str(backup))
        try:
            rule_engine._reset_c2_ports_cache()
            layered = rule_engine._load_c2_ports()  # 不得抛异常
            self.assertEqual(layered["high"],
                             rule_engine._C2_PORTS_FALLBACK_HIGH)
            self.assertEqual(layered["low"],
                             rule_engine._C2_PORTS_FALLBACK_LOW)
            self.assertEqual(len(layered["all"]), 11,
                             "降级后端口覆盖不得缩水")
        finally:
            shutil.move(str(backup), str(C2_PORTS_FILE))
            rule_engine._refresh_c2_ports()

    def test_ac_p2_4b_graceful_degradation_when_file_corrupt(self):
        """AC-P2-4 附加：SSOT 文件损坏时同样回落，不抛异常."""
        from app.rules import rule_engine

        original = C2_PORTS_FILE.read_text(encoding="utf-8")
        C2_PORTS_FILE.write_text("{ this is not valid json", encoding="utf-8")
        try:
            rule_engine._reset_c2_ports_cache()
            layered = rule_engine._load_c2_ports()
            self.assertEqual(len(layered["all"]), 11)
        finally:
            C2_PORTS_FILE.write_text(original, encoding="utf-8")
            rule_engine._refresh_c2_ports()

    def test_ac_p2_5_previously_missed_ports_now_hit(self):
        """AC-P2-5：原引擎漏判的 4443/5555/8888 现在能命中.

        用例经过隔离设计——系统目录 + 非解释器进程名，使 `_ANOMALOUS_NET_
        INTERPRETERS` 与 `non_system` 两个分支均为 False，命中只能来自
        C2 端口分支，从而精确证明端口清单生效。
        """
        from app.rules.rule_engine import RuleEngine

        rule = _behavior_rule("anomalous_network_process",
                              "anomalous_net_process")

        for port in sorted(LEGACY_JSON_PORTS - LEGACY_ENGINE_PORTS):
            with self.subTest(port=port):
                self.assertTrue(
                    RuleEngine.match_rule(
                        {
                            "name": "svchost.exe",
                            "path": "C:\\Windows\\System32\\svchost.exe",
                            "connections": [{"remote_port": port}],
                        },
                        rule,
                    ),
                    f"端口 {port} 此前被引擎漏判，SSOT 合并后应命中",
                )

    def test_ac_p2_5b_business_ports_still_not_flagged(self):
        """AC-P2-5 附加：合并端口清单不得把业务端口拖下水（误报防线）."""
        from app.rules.rule_engine import RuleEngine

        rule = _behavior_rule("anomalous_network_process",
                              "anomalous_net_process")
        for port in (80, 443, 53, 3389, 445):
            with self.subTest(port=port):
                self.assertFalse(
                    RuleEngine.match_rule(
                        {
                            "name": "svchost.exe",
                            "path": "C:\\Windows\\System32\\svchost.exe",
                            "connections": [{"remote_port": port}],
                        },
                        rule,
                    ),
                    f"业务端口 {port} 不应命中",
                )


# ══════════════════════════════════════════════════════════════════
# P2-2 严重度校准
# ══════════════════════════════════════════════════════════════════

class TestP2SeverityCalibration(unittest.TestCase):
    """AC-P2-6 ~ AC-P2-8."""

    @classmethod
    def setUpClass(cls):
        cls.rules = load_default_rules()
        cls.counter = collections.Counter(r["severity"] for r in cls.rules)

    def test_ac_p2_6_high_ratio_within_budget(self):
        """AC-P2-6：high 占比 ≤ 55%（闭合 P1 遗留的 AC-P1-13）."""
        ratio = self.counter["high"] / len(self.rules) * 100
        self.assertLessEqual(
            ratio, 55.0,
            f"high 占比 {ratio:.1f}% 超出预算（{self.counter['high']}/{len(self.rules)}）",
        )

    def test_ac_p2_7_measurement_scope_matches_production(self):
        """AC-P2-7：度量口径必须与生产装载一致（glob 全量，不得手工白名单）.

        P1 探针曾用 4 文件白名单，漏掉 default_attack_chain.json（10 条全
        critical），把 high 占比从 55.8% 虚高到 59.9%。此用例锁死口径。
        """
        globbed = {p.name for p in RULES_DIR.glob("*.json")} - set(DATA_FILES)
        counted = set()
        for jf in RULES_DIR.glob("*.json"):
            if jf.name in DATA_FILES:
                continue
            data = json.loads(jf.read_text(encoding="utf-8"))
            if isinstance(data, list):
                counted.add(jf.name)

        self.assertEqual(globbed, counted)
        self.assertIn("default_attack_chain.json", counted,
                      "attack_chain 文件必须计入严重度口径")

        total_entries = sum(
            len(json.loads((RULES_DIR / f).read_text(encoding="utf-8")))
            for f in counted
        )
        self.assertEqual(len(self.rules), total_entries,
                         "loader 返回数应等于全部规则文件条目数（0 跳过）")

    def test_ac_p2_8_critical_rules_require_hitl(self):
        """AC-P2-8：关键 critical 规则保持 critical 且带 requires_hitl 标注."""
        by_name = {r["name"]: r for r in self.rules}
        for name in sorted(CRITICAL_HITL_RULES):
            with self.subTest(rule=name):
                self.assertIn(name, by_name, f"关键规则 {name} 缺失")
                rule = by_name[name]
                self.assertEqual(
                    rule["severity"], "critical",
                    f"{name} 必须保持 critical",
                )
                meta = rule.get("condition", {}).get("_meta", {})
                self.assertIs(
                    meta.get("requires_hitl"), True,
                    f"{name} 缺少 _meta.requires_hitl 标注，"
                    "自动处置将绕过人工审批",
                )

    def test_ac_p2_8b_no_bare_process_name_high_rules_reintroduced(self):
        """AC-P2-8 附加：不得再引入"单端口/裸进程名 + high"的弱条件规则."""
        offenders = []
        for r in self.rules:
            if r["severity"] not in ("high", "critical"):
                continue
            if not r.get("enabled", True):
                continue
            cond = r.get("condition", {})
            if r.get("rule_type") == "list" and cond.get("field") in (
                    "remote_port", "dst_port", "port"):
                if len(cond.get("values", [])) <= 1:
                    offenders.append(r["name"])
        self.assertEqual(offenders, [],
                         f"发现单端口高危规则（应合并进 SSOT）: {offenders}")


# ══════════════════════════════════════════════════════════════════
# P2-3 装载可观测性
# ══════════════════════════════════════════════════════════════════

class TestP2LoaderObservability(unittest.TestCase):
    """AC-P2-9 ~ AC-P2-12."""

    def test_ac_p2_9_report_captures_invalid_rules(self):
        """AC-P2-9：LoadReport 必须报告各类非法规则及其原因."""
        tmpdir = Path(tempfile.mkdtemp(prefix="p2_rules_"))
        original_dir = loader.RULES_DIR
        try:
            # 1 条合法 + 5 条各类非法
            (tmpdir / "mixed.json").write_text(json.dumps([
                {"name": "ok_rule", "rule_type": "regex", "severity": "low",
                 "condition": {"field": "name", "pattern": "x"}},
                {"name": "bad_type", "rule_type": "no_such_type",
                 "severity": "low", "condition": {"field": "name",
                                                  "pattern": "x"}},
                {"name": "bad_sev", "rule_type": "regex",
                 "severity": "apocalyptic", "condition": {"field": "name",
                                                          "pattern": "x"}},
                {"rule_type": "regex", "severity": "low",
                 "condition": {"field": "name", "pattern": "x"}},
                {"name": "bad_cond", "rule_type": "regex", "severity": "low",
                 "condition": "not-an-object"},
                "i am not even an object",
            ], ensure_ascii=False), encoding="utf-8")

            loader.RULES_DIR = tmpdir
            rules, report = load_default_rules_with_report()

            self.assertEqual(len(rules), 1)
            self.assertEqual(rules[0]["name"], "ok_rule")
            self.assertEqual(report.total_entries, 6)
            self.assertEqual(report.loaded, 1)
            self.assertEqual(report.skipped_count, 5)

            reasons = " | ".join(s.reason for s in report.skipped)
            self.assertIn("rule_type 非法", reasons)
            self.assertIn("severity 非法", reasons)
            self.assertIn("缺少合法 name", reasons)
            self.assertIn("condition 非对象", reasons)
            self.assertIn("条目不是对象", reasons)

            # 明细须能定位到具体文件与下标
            for rec in report.skipped:
                self.assertEqual(rec.file, "mixed.json")
                self.assertGreaterEqual(rec.index, 0)

            payload = report.to_dict()
            self.assertEqual(payload["skipped"], 5)
            self.assertEqual(len(payload["skipped_detail"]), 5)
        finally:
            loader.RULES_DIR = original_dir
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_ac_p2_9b_report_handles_non_array_and_broken_files(self):
        """AC-P2-9 附加：非数组 / 解析失败的文件计入文件级跳过."""
        tmpdir = Path(tempfile.mkdtemp(prefix="p2_rules_"))
        original_dir = loader.RULES_DIR
        try:
            (tmpdir / "obj.json").write_text('{"not": "an array"}',
                                             encoding="utf-8")
            (tmpdir / "broken.json").write_text("{{{", encoding="utf-8")

            loader.RULES_DIR = tmpdir
            rules, report = load_default_rules_with_report()

            self.assertEqual(rules, [])
            self.assertEqual(report.skipped_count, 2)
            self.assertTrue(all(s.index == -1 for s in report.skipped))
            reasons = " | ".join(s.reason for s in report.skipped)
            self.assertIn("顶层不是数组", reasons)
            self.assertIn("文件解析失败", reasons)
        finally:
            loader.RULES_DIR = original_dir
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_ac_p2_10_data_files_produce_no_false_warning(self):
        """AC-P2-10：数据文件不再产生"顶层不是数组"假阳性告警.

        该告警每次启动都出现，会训练运维忽略此类 warning，从而掩盖真正的
        规则丢失。
        """
        with self.assertLogs(loader.logger, level="DEBUG") as cm:
            rules, report = load_default_rules_with_report()

        for name in DATA_FILES:
            if (RULES_DIR / name).exists():
                self.assertIn(name, report.data_files)

        joined = "\n".join(cm.output)
        for name in DATA_FILES:
            self.assertNotIn(f"规则文件 {name} 顶层不是数组", joined)

        # 数据文件不得计入跳过
        skipped_files = {s.file for s in report.skipped}
        self.assertEqual(skipped_files & set(DATA_FILES), set())

        # 生产规则目录当前应零跳过
        self.assertEqual(report.skipped_count, 0,
                         f"生产规则存在跳过项: {report.skipped}")
        self.assertEqual(report.loaded, len(rules))

    def test_ac_p2_11_orphans_reported_not_deleted(self):
        """AC-P2-11：DB 孤儿 default 规则被报告但绝不删除.

        孤儿可能是合法的第二套规则源（如 service_risk_analyzer 的 detector
        型规则 P0-1-TAMPER 等），自动删除会静默摧毁其检测能力。
        """
        from app.database import _import_default_rules

        tmpdb = Path(tempfile.mkdtemp(prefix="p2_db_")) / "t.db"
        conn = sqlite3.connect(str(tmpdb))
        conn.row_factory = sqlite3.Row
        conn.execute("""
            CREATE TABLE rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE, description TEXT, category TEXT,
                rule_type TEXT, condition TEXT, severity TEXT,
                enabled INTEGER DEFAULT 1, label TEXT, source TEXT,
                mitre_attack TEXT, engine_type TEXT
            )
        """)
        # 1 条孤儿（模拟 service_risk 内置规则）+ 1 条用户规则
        conn.execute(
            "INSERT INTO rules (name, rule_type, severity, condition, source) "
            "VALUES ('P0-1-TAMPER','behavior','critical','{}','default')")
        conn.execute(
            "INSERT INTO rules (name, rule_type, severity, condition, source) "
            "VALUES ('my_custom_rule','regex','low','{}','user')")
        conn.commit()

        try:
            stats = _import_default_rules(conn)
            conn.commit()

            self.assertIn("orphans", stats)
            self.assertIn("P0-1-TAMPER", stats["orphans"])
            self.assertNotIn("my_custom_rule", stats["orphans"],
                             "user 规则不属于 default 孤儿")

            # 关键：孤儿仍在库中，且内容未被改动
            row = conn.execute(
                "SELECT severity, source FROM rules WHERE name='P0-1-TAMPER'"
            ).fetchone()
            self.assertIsNotNone(row, "孤儿规则被误删！")
            self.assertEqual(row["severity"], "critical")

            # user 规则须被保留
            self.assertGreaterEqual(stats["preserved"], 1)
            row_u = conn.execute(
                "SELECT source FROM rules WHERE name='my_custom_rule'"
            ).fetchone()
            self.assertEqual(row_u["source"], "user")

            # 可观测字段齐备
            for key in ("total_entries", "skipped", "skipped_detail",
                        "data_files", "loaded"):
                self.assertIn(key, stats, f"stats 缺少 {key}")
            self.assertEqual(stats["total"], stats["loaded"],
                             "total 语义应保持为装载成功数（向后兼容）")
        finally:
            conn.close()
            shutil.rmtree(tmpdb.parent, ignore_errors=True)

    def test_ac_p2_12_backward_compatible_api(self):
        """AC-P2-12：load_default_rules() 原签名与返回值不变."""
        rules = load_default_rules()
        self.assertIsInstance(rules, list)
        self.assertTrue(all(isinstance(r, dict) for r in rules))

        rules2, report = load_default_rules_with_report()
        self.assertEqual([r["name"] for r in rules],
                         [r["name"] for r in rules2],
                         "两个 API 必须返回一致的规则序列")
        self.assertEqual(report.loaded, len(rules))

    def test_ac_p2_12b_summary_line_is_greppable(self):
        """AC-P2-12 附加：摘要行格式稳定，可被日志告警规则 grep."""
        _rules, report = load_default_rules_with_report()
        line = report.summary_line()
        self.assertTrue(line.startswith("[RULE-LOAD] "))
        for token in ("files=", "entries=", "loaded=", "skipped=", "orphans="):
            self.assertIn(token, line)


# ══════════════════════════════════════════════════════════════════
# P2-4 双管道对齐
# ══════════════════════════════════════════════════════════════════

class TestP2DualPipelineContract(unittest.TestCase):
    """AC-P2-13 ~ AC-P2-14."""

    def test_ac_p2_13_payload_shape_compatibility(self):
        """AC-P2-13：event_ids_summary 的三种载荷形态均能正确抽取."""
        from app.services.security_event_rules import extract_event_summary

        expected = {"4625": 12, "4662": 1}

        # 形态 1：单个采集结果对象
        self.assertEqual(
            extract_event_summary({"event_ids_summary": expected,
                                    "antivirus": []}),
            expected,
        )
        # 形态 2：列表包裹（import 链路常见）
        self.assertEqual(
            extract_event_summary([{"event_ids_summary": expected}]),
            expected,
        )
        # 形态 3：已剥离外层的裸计数字典（agent_imports.raw_json 反序列化后）
        self.assertEqual(extract_event_summary(expected), expected)

    def test_ac_p2_13b_malformed_payload_degrades_safely(self):
        """AC-P2-13 附加：畸形载荷不得抛异常."""
        from app.services.security_event_rules import extract_event_summary

        for payload in (None, {}, [], "string", 42, {"event_ids_summary": None},
                        {"event_ids_summary": "not-a-dict"}, [[]]):
            with self.subTest(payload=payload):
                result = extract_event_summary(payload)
                self.assertIsInstance(result, dict)

    def test_ac_p2_14_evaluate_degrades_without_rules(self):
        """AC-P2-14：无 event_log_summary 规则 / 空 summary 时优雅降级."""
        from app.services.security_event_rules import evaluate_summary

        self.assertEqual(evaluate_summary({}), [])
        self.assertEqual(evaluate_summary({"4625": 99}, rules=[]), [])
        self.assertEqual(evaluate_summary(None), [])

    def test_ac_p2_14b_evaluate_matches_builtin_rules(self):
        """AC-P2-14 附加：桥接链路端到端可命中（4662 DCSync 阈值 >=1）."""
        from app.services.security_event_rules import (
            _load_builtin_rules,
            evaluate_summary,
        )

        builtin = _load_builtin_rules()
        self.assertTrue(builtin, "内置 event_log_rules.json 应可读")

        hits = evaluate_summary({"4662": 3}, rules=builtin)
        names = {h.get("name") for h in hits}
        self.assertIn("evt_4662_dcsync_suspect", names)

        # 低于阈值不得命中（4625 需 >=10）
        hits_low = evaluate_summary({"4625": 2}, rules=builtin)
        self.assertNotIn("evt_4625_failed_logon_burst",
                         {h.get("name") for h in hits_low})

    def test_ac_p2_13c_rule_coverage_matches_design(self):
        """AC-P2-13 附加：6 个设计目标事件 ID 均有规则覆盖."""
        data = json.loads(
            (RULES_DIR / "event_log_rules.json").read_text(encoding="utf-8"))
        covered = set()
        for r in data:
            cond = r.get("condition", {})
            if cond.get("event_id") is not None:
                covered.add(int(cond["event_id"]))
            for eid in cond.get("event_ids", []) or []:
                covered.add(int(eid))

        self.assertEqual(covered, {4624, 4625, 4648, 4662, 4672, 4769})


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    unittest.main(verbosity=2)
