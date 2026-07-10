#!/usr/bin/env python3
"""攻击链关联检测（任务①）单元测试.

覆盖：
  - schema: validate_condition 对 attack_chain 的校验（合法/非法结构）
  - 引擎: _match_attack_chain 贪心顺序匹配 + 时间窗判定
  - 集成: RuleEngine.evaluate 主机级命中强制 severity=critical，reason 含步骤明细
  - 默认规则: loader 加载 default_attack_chain.json 且不报错
"""

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.rules.rule_engine import RuleEngine  # noqa: E402
from app.schemas.analysis import validate_condition, RULE_TYPE_ENUM  # noqa: E402


def _ac_rule(window_minutes=60, steps=None):
    return {
        "name": "test_chain",
        "rule_type": "attack_chain",
        "severity": "high",  # 引擎应强制覆盖为 critical
        "condition": {
            "window_minutes": window_minutes,
            "host_scope": "single",
            "ordered_steps": steps
            or [
                {"step": 1, "dimension": "process",
                 "match": {"type": "regex", "field": "command_line",
                           "pattern": "powershell.*-enc"}},
                {"step": 2, "dimension": "connection",
                 "match": {"type": "list", "field": "remote_address",
                           "values": ["c2.example.com"], "match_mode": "exact"}},
                {"step": 3, "dimension": "registry",
                 "match": {"type": "regex", "field": "key_path",
                           "pattern": "(?i).*Run"}},
            ],
        },
    }


def _ev(dimension, data, ts=None):
    return {"dimension": dimension, "timestamp": ts, "data": data}


class TestAttackChainSchema(unittest.TestCase):
    """schema / validate_condition 校验."""

    def test_enum_registered(self):
        self.assertIn("attack_chain", RULE_TYPE_ENUM)

    def test_valid_condition_passes(self):
        validate_condition("attack_chain", _ac_rule()["condition"])  # 不应抛异常

    def test_missing_ordered_steps_raises(self):
        cond = {"window_minutes": 60, "host_scope": "single"}
        with self.assertRaises(ValueError):
            validate_condition("attack_chain", cond)

    def test_empty_ordered_steps_raises(self):
        cond = {"ordered_steps": [], "window_minutes": 60}
        with self.assertRaises(ValueError):
            validate_condition("attack_chain", cond)

    def test_invalid_dimension_raises(self):
        cond = {"ordered_steps": [
            {"step": 1, "dimension": "bogus", "match": {"type": "exists", "field": "x"}}
        ]}
        with self.assertRaises(ValueError):
            validate_condition("attack_chain", cond)

    def test_step_missing_match_raises(self):
        cond = {"ordered_steps": [
            {"step": 1, "dimension": "process", "match": {"type": ""}}
        ]}
        with self.assertRaises(ValueError):
            validate_condition("attack_chain", cond)

    def test_window_minutes_upper_bound(self):
        cond = _ac_rule(window_minutes=1441)["condition"]
        with self.assertRaises(ValueError):
            validate_condition("attack_chain", cond)
        # 边界 1440 合法
        validate_condition("attack_chain", _ac_rule(window_minutes=1440)["condition"])

    def test_window_minutes_non_int_raises(self):
        cond = _ac_rule(window_minutes="abc")["condition"]
        with self.assertRaises(ValueError):
            validate_condition("attack_chain", cond)


class TestAttackChainEngine(unittest.TestCase):
    """引擎层 _match_attack_chain 逻辑（直接注入事件，无需 DB）."""

    def test_in_window_ordered_match(self):
        t = datetime(2026, 7, 11, 10, 0, 0)
        events = [
            _ev("process", {"command_line": "powershell -enc AAA"}, t),
            _ev("connection", {"remote_address": "c2.example.com"}, t + timedelta(minutes=5)),
            _ev("registry", {"key_path": "HKLM\\Software\\Microsoft\\Windows\\CurrentVersion\\Run"}, t + timedelta(minutes=10)),
        ]
        result = RuleEngine._match_attack_chain(_ac_rule(), {"host_id": 1}, host_events=events)
        self.assertIsNotNone(result)
        self.assertEqual(len(result["steps"]), 3)
        self.assertIn("步骤", result["reason"])

    def test_out_of_order_no_match(self):
        # 步骤顺序要求 process→connection→registry，但事件时间顺序反了
        t = datetime(2026, 7, 11, 10, 0, 0)
        events = [
            _ev("registry", {"key_path": "HKLM\\...\\Run"}, t),
            _ev("connection", {"remote_address": "c2.example.com"}, t + timedelta(minutes=5)),
            _ev("process", {"command_line": "powershell -enc AAA"}, t + timedelta(minutes=10)),
        ]
        result = RuleEngine._match_attack_chain(_ac_rule(), {"host_id": 1}, host_events=events)
        self.assertIsNone(result)

    def test_over_window_no_match(self):
        t = datetime(2026, 7, 11, 10, 0, 0)
        events = [
            _ev("process", {"command_line": "powershell -enc AAA"}, t),
            _ev("connection", {"remote_address": "c2.example.com"}, t + timedelta(minutes=30)),
            _ev("registry", {"key_path": "HKLM\\...\\Run"}, t + timedelta(minutes=70)),
        ]
        result = RuleEngine._match_attack_chain(_ac_rule(60), {"host_id": 1}, host_events=events)
        self.assertIsNone(result)

    def test_missing_step_no_match(self):
        t = datetime(2026, 7, 11, 10, 0, 0)
        events = [
            _ev("process", {"command_line": "powershell -enc AAA"}, t),
            # connection 步骤缺失
            _ev("registry", {"key_path": "HKLM\\...\\Run"}, t + timedelta(minutes=10)),
        ]
        result = RuleEngine._match_attack_chain(_ac_rule(), {"host_id": 1}, host_events=events)
        self.assertIsNone(result)

    def test_exists_step_match(self):
        rule = {
            "name": "exists_chain", "rule_type": "attack_chain", "severity": "high",
            "condition": {"window_minutes": 60, "ordered_steps": [
                {"step": 1, "dimension": "persistence",
                 "match": {"type": "exists", "field": "command"}},
                {"step": 2, "dimension": "ioc",
                 "match": {"type": "list", "field": "ioc_value",
                           "values": ["1.2.3.4"], "match_mode": "exact"}},
            ]},
        }
        t = datetime(2026, 7, 11, 10, 0, 0)
        events = [
            _ev("persistence", {"command": "malware.exe"}, t),
            _ev("ioc", {"ioc_value": "1.2.3.4"}, t + timedelta(minutes=2)),
        ]
        result = RuleEngine._match_attack_chain(rule, {"host_id": 1}, host_events=events)
        self.assertIsNotNone(result)
        self.assertEqual(len(result["steps"]), 2)


class TestAttackChainIntegration(unittest.TestCase):
    """RuleEngine.evaluate 主机级命中强制 critical."""

    def test_evaluate_forces_critical_and_steps(self):
        t = datetime(2026, 7, 11, 10, 0, 0)
        events = [
            _ev("process", {"command_line": "powershell -enc AAA"}, t),
            _ev("connection", {"remote_address": "c2.example.com"}, t + timedelta(minutes=5)),
            _ev("registry", {"key_path": "HKLM\\...\\Run"}, t + timedelta(minutes=10)),
        ]

        # 用 monkeypatch 直接注入事件，避免依赖 DB
        orig = RuleEngine._build_host_events
        RuleEngine._build_host_events = staticmethod(lambda gc: events)
        try:
            matches = RuleEngine.evaluate(
                [], [_ac_rule()], global_context={"host_id": 1}
            )
        finally:
            RuleEngine._build_host_events = staticmethod(orig)

        self.assertEqual(len(matches), 1)
        m = matches[0]
        self.assertEqual(m["severity"], "critical")  # 强制覆盖
        self.assertEqual(m["rule_name"], "test_chain")
        self.assertIn("attack_chain_steps", m["item"])
        self.assertEqual(len(m["item"]["attack_chain_steps"]), 3)
        self.assertTrue(m["item"]["_attack_chain"])

    def test_evaluate_skips_when_no_host_id(self):
        orig = RuleEngine._build_host_events
        RuleEngine._build_host_events = staticmethod(lambda gc: [])
        try:
            matches = RuleEngine.evaluate(
                [], [_ac_rule()], global_context={}
            )
        finally:
            RuleEngine._build_host_events = staticmethod(orig)
        self.assertEqual(matches, [])


class TestAttackChainDefaultRule(unittest.TestCase):
    """loader 加载默认攻击链规则."""

    def test_loader_includes_default_attack_chain(self):
        from app.rules.loader import load_default_rules
        rules = load_default_rules()
        names = [r.get("name") for r in rules]
        self.assertIn("attack_chain_default_c2_persistence", names)
        ac = [r for r in rules if r.get("name") == "attack_chain_default_c2_persistence"][0]
        self.assertEqual(ac["rule_type"], "attack_chain")
        # 其 condition 应通过校验（loader 已校验，这里再验一次双重保险）
        validate_condition("attack_chain", ac["condition"])


if __name__ == "__main__":
    unittest.main()
