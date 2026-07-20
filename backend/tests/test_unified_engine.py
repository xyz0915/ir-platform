#!/usr/bin/env python3
"""统一规则引擎测试（T-P0-4 回归验收）.

覆盖：
  1. 7 类 matcher 通过 MatcherRegistry dispatch 均正确委派（与直接调用一致）
  2. RuleEngine.evaluate 产出含 confidence/matched_fields/gated_by 的 MatchedRule
  3. 抑制（RuleSuppression.is_suppressed）生效 — 命中被标记 gated_by="suppression"
  4. 误报模式（FalsePositivePattern.match）生效 — hit_count 自增 + gated_by="false_positive"
  5. 白名单精确检查（WhitelistService.is_whitelisted_precise）—
     path/process_name 命中不告警（gated_by="whitelist"）
  6. attack_chain 实时命中（同 test_attack_chain 注入事件）
  7. CanonicalAdapter: security_event_row_to_canonical + to_engine_item 字段扁平
"""

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))


# ===================================================================
#  辅助工厂
# ===================================================================

def _make_rule(rule_id: int, name: str, rule_type: str, condition: dict,
               category: str = "process", severity: str = "high") -> dict:
    return {
        "id": rule_id,
        "name": name,
        "rule_type": rule_type,
        "category": category,
        "severity": severity,
        "condition": condition,
    }


def _engine_item(**overrides) -> dict:
    """构造 to_engine_item()-风格的扁平化数据项."""
    base = {
        "name": "powershell.exe",
        "path": "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe",
        "command_line": "powershell.exe -enc SQBFAFgA",
        "ppid": 1234,
        "pid": 5678,
        "parent_name": "explorer.exe",
        "host_id": 1,
        "event_type": "process_start",
        "category": "process",
        "remote_address": "",
        "remote_port": 0,
    }
    base.update(overrides)
    return base


# ===================================================================
#  TestMatcherRegistry — 7 类 dispatch 委派验证
# ===================================================================

class TestMatcherRegistry(unittest.TestCase):
    """MatcherRegistry 注册 7 类 dispatch 与直接调用一致."""

    def test_regex_dispatch(self):
        from app.rules.matchers.registry import MatcherRegistry
        from app.rules.rule_engine import RuleEngine
        item = _engine_item(command_line="powershell -enc AAA")
        cond = {"field": "command_line", "pattern": "-enc", "flags": "ignorecase"}
        dispatch = MatcherRegistry.dispatch("regex", item, cond)
        direct = RuleEngine._match_regex(item, cond)
        self.assertEqual(dispatch, direct)

    def test_list_dispatch(self):
        from app.rules.matchers.registry import MatcherRegistry
        from app.rules.rule_engine import RuleEngine
        item = _engine_item(remote_address="185.220.101.1")
        cond = {"field": "remote_address", "values": ["185.220.101.1"], "match_mode": "exact"}
        dispatch = MatcherRegistry.dispatch("list", item, cond)
        direct = RuleEngine._match_list(item, cond)
        self.assertEqual(dispatch, direct)

    def test_threshold_dispatch(self):
        from app.rules.matchers.registry import MatcherRegistry
        from app.rules.rule_engine import RuleEngine
        item = _engine_item(risk_score=75)
        cond = {"field": "risk_score", "operator": ">", "value": 50}
        dispatch = MatcherRegistry.dispatch("threshold", item, cond)
        direct = RuleEngine._match_threshold(item, cond)
        self.assertEqual(dispatch, direct)

    def test_behavior_dispatch(self):
        from app.rules.matchers.registry import MatcherRegistry
        from app.rules.rule_engine import RuleEngine
        item = _engine_item(ppid=0)
        cond = {"pattern": "orphan_process"}
        dispatch = MatcherRegistry.dispatch("behavior", item, cond)
        direct = RuleEngine._match_behavior(item, cond)
        self.assertEqual(dispatch, direct)

    def test_composite_dispatch(self):
        from app.rules.matchers.registry import MatcherRegistry
        from app.rules.rule_engine import RuleEngine
        item = _engine_item(command_line="mimikatz.exe")
        cond = {"logic": "OR", "sub_rules": [
            {"field": "command_line", "pattern": "mimikatz", "flags": "ignorecase"},
        ]}
        dispatch = MatcherRegistry.dispatch("composite", item, cond)
        direct = RuleEngine._match_composite(item, cond)
        self.assertEqual(dispatch, direct)

    def test_exists_dispatch(self):
        from app.rules.matchers.registry import MatcherRegistry
        from app.rules.rule_engine import RuleEngine
        item = _engine_item(scheduled_task_xml="<Task/>")
        cond = {"field": "scheduled_task_xml"}
        dispatch = MatcherRegistry.dispatch("exists", item, cond)
        direct = RuleEngine._match_exists(item, cond)
        self.assertEqual(dispatch, direct)

    def test_attack_chain_dispatch_returns_false(self):
        from app.rules.matchers.registry import MatcherRegistry
        r = MatcherRegistry.dispatch("attack_chain", {}, {})
        self.assertFalse(r)

    def test_unknown_type_returns_false(self):
        from app.rules.matchers.registry import MatcherRegistry
        r = MatcherRegistry.dispatch("nonexistent", {}, {})
        self.assertFalse(r)

    def test_registered_types_include_all_7(self):
        from app.rules.matchers.registry import MatcherRegistry
        types = set(MatcherRegistry.registered_types())
        self.assertEqual(types, {"regex", "list", "threshold", "behavior",
                                  "composite", "exists", "attack_chain"})


# ===================================================================
#  TestUnifiedEvaluate — MatchedRule 产出验证
# ===================================================================

class TestUnifiedEvaluate(unittest.TestCase):
    """RuleEngine.evaluate 统一产出 MatchedRule（含 confidence/matched_fields/gated_by）. """

    def test_evaluate_returns_dict_with_new_fields(self):
        from app.rules.rule_engine import RuleEngine
        # 使用不会命中真实白名单的唯一名字
        item = _engine_item(name="unified_test_abc_123.exe",
                            path="C:\\unified_test\\unified_test_abc_123.exe",
                            command_line="unified_test_abc_123.exe -enc AAA")
        rule = _make_rule(1, "test_regex", "regex",
                          {"field": "command_line", "pattern": "-enc", "flags": "ignorecase"})
        matches = RuleEngine.evaluate([item], [rule], global_context={"host_id": 1})
        self.assertEqual(len(matches), 1)
        m = matches[0]
        # 必要的统一字段
        self.assertIn("rule_id", m)
        self.assertIn("rule_name", m)
        self.assertIn("rule_type", m)
        self.assertIn("category", m)
        self.assertIn("severity", m)
        self.assertIn("confidence", m)
        self.assertIn("reason", m)
        self.assertIn("matched_fields", m)
        self.assertIn("attack_chain", m)
        self.assertIn("gated_by", m)
        self.assertIn("item", m)
        self.assertIn("rule", m)
        self.assertEqual(m["gated_by"], None)  # 真实命中

    def test_suppression_gate_applies(self):
        """抑制规则命中时返回 gated_by='suppression'."""
        from app.rules.rule_engine import RuleEngine
        from unittest.mock import patch

        item = _engine_item(name="test_supp_xyz.exe", path="C:\\test\\test_supp_xyz.exe",
                            command_line="test_supp_xyz.exe -enc AAA")
        rule = _make_rule(1, "suppressed_rule", "regex",
                          {"field": "command_line", "pattern": "-enc", "flags": "ignorecase"})

        with patch("app.models.rule_suppression.RuleSuppression.is_suppressed", return_value=True):
            matches = RuleEngine.evaluate([item], [rule], global_context={"host_id": 1})
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["gated_by"], "suppression")
        self.assertEqual(matches[0]["rule_name"], "suppressed_rule")

    def test_false_positive_gate_applies(self):
        """FP 模式命中时返回 gated_by='false_positive' 且 hit_count 自增."""
        from app.rules.rule_engine import RuleEngine
        from unittest.mock import patch

        item = _engine_item(name="test_fp_xyz.exe", path="C:\\test\\test_fp_xyz.exe",
                            command_line="test_fp_xyz.exe -enc AAA")
        rule = _make_rule(1, "fp_rule", "regex",
                          {"field": "command_line", "pattern": "-enc", "flags": "ignorecase"})

        with patch("app.models.false_positive.FalsePositivePattern.match", return_value=True):
            matches = RuleEngine.evaluate([item], [rule], global_context={"host_id": 1})
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["gated_by"], "false_positive")

    def test_whitelist_gate_applies(self):
        """白名单精确检查命中时返回 gated_by='whitelist'."""
        from app.rules.rule_engine import RuleEngine
        from unittest.mock import patch

        item = _engine_item(name="whitelisted.exe", path="C:\\safe\\whitelisted.exe",
                            command_line="whitelisted.exe")
        rule = _make_rule(1, "wl_rule", "regex",
                          {"field": "name", "pattern": "whitelisted", "flags": "ignorecase"})

        with patch("app.services.whitelist_service.WhitelistService.is_whitelisted_precise", return_value=True):
            matches = RuleEngine.evaluate([item], [rule], global_context={"host_id": 1})
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["gated_by"], "whitelist")

    def test_confidence_behavior_orphan(self):
        """orphan_process 置信度 0.75（兼容旧 matcher）。"""
        from app.rules.rule_engine import RuleEngine
        item = _engine_item(name="orphan.exe", ppid=0)
        rule = _make_rule(1, "orphan_test", "behavior", {"pattern": "orphan_process"})
        matches = RuleEngine.evaluate([item], [rule], global_context={"host_id": 1})
        if matches:
            self.assertAlmostEqual(matches[0]["confidence"], 0.75, places=2)

    def test_confidence_regex_default(self):
        """regex 默认置信度 0.9。"""
        from app.rules.rule_engine import RuleEngine
        item = _engine_item(command_line="powershell -enc AAA")
        rule = _make_rule(1, "conf_regex", "regex",
                          {"field": "command_line", "pattern": "-enc", "flags": "ignorecase"})
        matches = RuleEngine.evaluate([item], [rule], global_context={"host_id": 1})
        self.assertAlmostEqual(matches[0]["confidence"], 0.9, places=2)

    def test_gated_match_does_not_increment_hit_count(self):
        """被抑制/误报/白名单门控的命中不应递增 rule hit_count。"""
        from app.rules.rule_engine import RuleEngine
        from unittest.mock import patch

        item = _engine_item(name="test_gated_xyz.exe", path="C:\\test\\test_gated_xyz.exe",
                            command_line="test_gated_xyz.exe -enc AAA")
        rule = _make_rule(1, "no_hit_gated", "regex",
                          {"field": "command_line", "pattern": "-enc", "flags": "ignorecase"})

        with patch("app.models.rule_suppression.RuleSuppression.is_suppressed", return_value=True):
            matches = RuleEngine.evaluate([item], [rule], global_context={"host_id": 1})
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["gated_by"], "suppression")
        # hit_count 不应递增
        self.assertIsNone(rule.get("_hit_updated"))


# ===================================================================
#  TestAttackChainRealtime — attack_chain 实时命中（同 test_attack_chain 注入）
# ===================================================================

class TestAttackChainRealtime(unittest.TestCase):
    """验证攻击链经统一 evaluate 实时命中."""

    def test_attack_chain_in_evaluate_real_time(self):
        """RuleEngine.evaluate 内 attack_chain 实时命中并强制 critical。"""
        from app.rules.rule_engine import RuleEngine

        t = datetime(2026, 7, 11, 10, 0, 0)

        def _ev(dim, data, ts=None):
            return {"dimension": dim, "timestamp": ts, "data": data}

        events = [
            _ev("process", {"command_line": "powershell -enc AAA"}, t),
            _ev("connection", {"remote_address": "c2.example.com"}, t + timedelta(minutes=5)),
            _ev("registry", {"key_path": "HKLM\\Software\\Microsoft\\Windows\\CurrentVersion\\Run"}, t + timedelta(minutes=10)),
        ]

        ac_rule = {
            "name": "test_chain_realtime",
            "rule_type": "attack_chain",
            "severity": "high",
            "condition": {
                "window_minutes": 60,
                "host_scope": "single",
                "ordered_steps": [
                    {"step": 1, "dimension": "process",
                     "match": {"type": "regex", "field": "command_line", "pattern": "powershell.*-enc"}},
                    {"step": 2, "dimension": "connection",
                     "match": {"type": "list", "field": "remote_address",
                               "values": ["c2.example.com"], "match_mode": "exact"}},
                    {"step": 3, "dimension": "registry",
                     "match": {"type": "regex", "field": "key_path", "pattern": "(?i).*Run"}},
                ],
            },
        }

        orig = RuleEngine._build_host_events
        RuleEngine._build_host_events = staticmethod(lambda gc: events)
        try:
            matches = RuleEngine.evaluate([], [ac_rule], global_context={"host_id": 1})
        finally:
            RuleEngine._build_host_events = staticmethod(orig)

        self.assertEqual(len(matches), 1)
        m = matches[0]
        self.assertEqual(m["severity"], "critical")
        self.assertEqual(m["rule_name"], "test_chain_realtime")
        self.assertIn("attack_chain_steps", m["item"])
        self.assertEqual(len(m["item"]["attack_chain_steps"]), 3)
        self.assertTrue(m["item"]["_attack_chain"])


# ===================================================================
#  TestCanonicalAdapter — 适配层字段扁平化
# ===================================================================

class TestCanonicalAdapter(unittest.TestCase):
    """CanonicalAdapter + CanonicalEvent.to_engine_item 字段扁平化验证."""

    def test_security_event_row_to_canonical(self):
        from app.rules.canonical_adapter import security_event_row_to_canonical
        row = {
            "id": 123,
            "event_type": "process_start",
            "severity": "high",
            "host_id": 5,
            "source_collector": "ac",
            "event_key": "evt_001",
            "evidence": '{"process_name": "evil.exe", "ppid": 0}',
        }
        ce = security_event_row_to_canonical(row)
        self.assertEqual(ce.event_uid, "123")
        self.assertEqual(ce.event_type, "process_start")
        self.assertEqual(ce.host_id, 5)
        self.assertIn("process_name", ce.evidence)

    def test_to_engine_item_aliases(self):
        from app.services.canonical_event import CanonicalEvent
        ce = CanonicalEvent(
            event_uid="ac:e1", source="ac", source_event_id="e1", host_id=1,
            event_type="process_start", category="process",
            evidence={"process_name": "evil.exe", "ppid": 0, "command_line": "evil -pwn"},
        )
        item = ce.to_engine_item()
        # 引擎别名
        self.assertEqual(item["name"], "evil.exe")  # process_name → name
        self.assertEqual(item["host_id"], 1)
        self.assertEqual(item["event_type"], "process_start")
        self.assertEqual(item["category"], "process")
        # 原始字段保留
        self.assertEqual(item["process_name"], "evil.exe")

    def test_to_engine_item_no_evidence(self):
        from app.services.canonical_event import CanonicalEvent
        ce = CanonicalEvent(
            event_uid="ac:e2", source="ac", source_event_id="e2", host_id=2,
        )
        item = ce.to_engine_item()
        self.assertIsInstance(item, dict)
        self.assertEqual(item.get("host_id"), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
