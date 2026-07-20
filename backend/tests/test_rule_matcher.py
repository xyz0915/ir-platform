"""规则匹配引擎测试 — 覆盖 7 种规则类型的 10 个测试用例.

测试范围:
  1. regex 匹配      — 命令行 Base64 编码检测
  2. list 匹配       — C2 端口/IP 黑名单检测
  3. composite AND   — powershell + -enc 组合匹配
  4. composite OR    — 子规则任匹配
  5. behavior 孤儿进程 — orphan_process 检测
  6. behavior 浏览器子进程 — child_of_browser 检测
  7. threshold 阈值  — risk_score > 50 阈值检测
  8. exists 字段存在性 — scheduled_task_xml 存在检测
  9. 无匹配          — 正常登录事件不应命中任何规则
  10. 多规则匹配     — 一个事件同时命中多个规则

使用方法:
    pytest backend/tests/test_rule_matcher.py -v
"""

from __future__ import annotations

import sys
sys.path.insert(0, '.')

import json
import unittest
from unittest.mock import patch

from app.services.rule_matcher import (
    match_event,
    _match_regex,
    _match_list,
    _match_composite,
    _match_behavior,
    _match_threshold,
    _match_exists,
    _parse_evidence,
    _get_nested,
)

# ===================================================================
#  辅助：模拟规则工厂
# ===================================================================


def _make_rule(rule_id: int, name: str, rule_type: str, condition: dict,
               category: str = "process", severity: str = "high") -> dict:
    """构造一条模拟规则字典（与数据库返回格式一致）。"""
    return {
        "id": rule_id,
        "name": name,
        "rule_type": rule_type,
        "category": category,
        "severity": severity,
        "condition": condition,
    }


def _make_event(event_type: str, evidence: dict, severity: str = "info",
                host_id: int = 1, event_id: str = "evt_001") -> dict:
    """构造一个模拟事件字典。"""
    return {
        "id": event_id,
        "event_type": event_type,
        "severity": severity,
        "evidence": evidence,
        "host_id": host_id,
    }


# ===================================================================
#  测试用例
# ===================================================================


class TestRuleMatcher(unittest.TestCase):
    """规则匹配引擎单元测试 —— 7 种规则类型 × 10 个场景."""

    # ── 1. regex 匹配：命令行 Base64 编码检测 ─────────────────────

    def test_regex_base64_detection(self):
        """regex: 命令行包含 Base64 编码字符串时应命中。"""
        rule = _make_rule(
            rule_id=1,
            name="base64_encoded_command",
            rule_type="regex",
            condition={
                "field": "command_line",
                "pattern": r"[A-Za-z0-9+/]{40,}={0,2}",
                "flags": "ignorecase",
            },
        )
        evidence = {
            "command_line": (
                "powershell -enc SQBuAHYAbwBrAGUALQBXAGUAYgBSAGUAcQB1AGUAcwB0AA=="
            ),
        }
        result = _match_regex(rule["condition"], evidence)
        self.assertIsNotNone(result)
        self.assertIn("matched_fields", result)
        self.assertIn("command_line", result["matched_fields"])
        self.assertAlmostEqual(result["confidence"], 0.9)

    # ── 2. list 匹配：C2 端口检测 ────────────────────────────────

    def test_list_c2_port_detection(self):
        """list: 远程地址命中已知 C2 IP 时应命中。"""
        rule = _make_rule(
            rule_id=2,
            name="suspicious_c2_domain",
            rule_type="list",
            condition={
                "field": "remote_address",
                "values": ["185.220.101.1", "malware-c2.example.com"],
                "match_mode": "exact",
            },
        )
        evidence = {
            "remote_address": "185.220.101.1",
            "remote_port": 4444,
        }
        result = _match_list(rule["condition"], evidence)
        self.assertIsNotNone(result)
        self.assertEqual(result["confidence"], 1.0)
        self.assertIn("remote_address", result["matched_fields"])

    # ── 3. composite AND：powershell + -enc 组合 ────────────────

    def test_composite_and_powershell_enc(self):
        """composite AND: 同时匹配 powershell.exe 名称 AND -enc 参数。"""
        rule = _make_rule(
            rule_id=3,
            name="powershell_encoded_command",
            rule_type="composite",
            condition={
                "logic": "AND",
                "sub_rules": [
                    {
                        "type": "regex",
                        "field": "process_name",
                        "pattern": r"powershell\.exe",
                        "flags": "ignorecase",
                    },
                    {
                        "type": "regex",
                        "field": "command_line",
                        "pattern": r"-enc",
                        "flags": "ignorecase",
                    },
                ],
            },
        )
        evidence = {
            "process_name": "powershell.exe",
            "command_line": (
                'powershell.exe -enc SQBuAHYAbwBrAGUALQBXAGUAYgBSAGUAcQB1AGUAcwB0AA=='
            ),
        }
        result = _match_composite(rule["condition"], evidence)
        self.assertIsNotNone(result)
        self.assertIn("command_line", result["matched_fields"])

    # ── 4. composite OR：子规则任匹配 ────────────────────────────

    def test_composite_or_any_subrule(self):
        """composite OR: 至少一个子规则匹配即命中。"""
        rule = _make_rule(
            rule_id=4,
            name="suspicious_tool_indicators",
            rule_type="composite",
            condition={
                "logic": "OR",
                "sub_rules": [
                    {
                        "type": "regex",
                        "field": "command_line",
                        "pattern": r"mimikatz",
                        "flags": "ignorecase",
                    },
                    {
                        "type": "regex",
                        "field": "command_line",
                        "pattern": r"procdump",
                        "flags": "ignorecase",
                    },
                ],
            },
        )
        # 仅命中 mimikatz
        evidence_mimi = {"command_line": "mimikatz.exe sekurlsa::logonpasswords"}
        result_mimi = _match_composite(rule["condition"], evidence_mimi)
        self.assertIsNotNone(result_mimi)

        # 仅命中 procdump
        evidence_proc = {"command_line": "procdump64.exe -accepteula -ma lsass.exe"}
        result_proc = _match_composite(rule["condition"], evidence_proc)
        self.assertIsNotNone(result_proc)

        # 都不命中
        evidence_clean = {"command_line": "notepad.exe readme.txt"}
        result_clean = _match_composite(rule["condition"], evidence_clean)
        self.assertIsNone(result_clean)

    # ── 5. behavior 孤儿进程 ─────────────────────────────────────

    def test_behavior_orphan_process(self):
        """behavior orphan_process: ppid==0 的进程应判定为孤儿进程。"""
        condition = {"pattern": "orphan_process"}
        evidence = {
            "process_name": "suspicious.exe",
            "ppid": 0,
            "parent_name": "",
        }
        event = _make_event("process_start", evidence)
        result = _match_behavior(condition, evidence, event)
        self.assertIsNotNone(result)
        self.assertEqual(result["confidence"], 0.75)
        self.assertIn("ppid", result["matched_fields"])

    # ── 6. behavior 浏览器子进程 ─────────────────────────────────

    def test_behavior_child_of_browser(self):
        """behavior child_of_browser: 父进程为 chrome 时应命中。"""
        condition = {"pattern": "child_of_browser"}
        evidence = {
            "process_name": "powershell.exe",
            "parent_name": "chrome.exe",
            "command_line": "powershell.exe -nop -w hidden -c IEX",
        }
        event = _make_event("process_start", evidence)
        result = _match_behavior(condition, evidence, event)
        self.assertIsNotNone(result)
        self.assertEqual(result["confidence"], 0.80)
        self.assertIn("parent_name", result["matched_fields"])

    # ── 7. threshold 阈值 ────────────────────────────────────────

    def test_threshold_risk_score(self):
        """threshold: risk_score > 50 时应命中，≤50 时应不命中。"""
        condition = {"field": "risk_score", "operator": ">", "value": 50}

        # 高于阈值
        event_high = _make_event("network_outbound", {"risk_score": 75})
        result_high = _match_threshold(condition, event_high, event_high.get("evidence", {}))
        self.assertIsNotNone(result_high)
        self.assertEqual(result_high["confidence"], 0.8)

        # 等于阈值（不命中）
        event_equal = _make_event("network_outbound", {"risk_score": 50})
        result_equal = _match_threshold(condition, event_equal, event_equal.get("evidence", {}))
        self.assertIsNone(result_equal)

        # 低于阈值（不命中）
        event_low = _make_event("network_outbound", {"risk_score": 30})
        result_low = _match_threshold(condition, event_low, event_low.get("evidence", {}))
        self.assertIsNone(result_low)

    # ── 8. exists 字段存在性 ─────────────────────────────────────

    def test_exists_field(self):
        """exists: 指定字段存在且非空时应命中。"""
        condition = {"field": "scheduled_task_xml"}

        # 字段存在
        evidence_present = {"scheduled_task_xml": "<Task><Triggers/></Task>"}
        result = _match_exists(condition, evidence_present)
        self.assertIsNotNone(result)
        self.assertEqual(result["confidence"], 0.7)
        self.assertEqual(result["matched_fields"]["scheduled_task_xml"], "present")

        # 字段不存在
        evidence_missing = {"command_line": "notepad.exe"}
        result_missing = _match_exists(condition, evidence_missing)
        self.assertIsNone(result_missing)

        # 字段为空字符串
        evidence_empty = {"scheduled_task_xml": ""}
        result_empty = _match_exists(condition, evidence_empty)
        self.assertIsNone(result_empty)

    # ── 9. 无匹配（正常登录事件）─────────────────────────────────

    @patch("app.services.rule_matcher._get_candidate_rules")
    def test_no_match_normal_login(self, mock_get_candidates):
        """正常登录事件不应命中任何规则（使用旧 matcher 灰度路径确保无回归）。"""
        import app.services.rule_matcher as _rm
        _rm.USE_UNIFIED_ENGINE = False
        # 模拟候选规则列表 — 返回几条规则但都不该匹配登录事件
        mock_get_candidates.return_value = [
            _make_rule(1, "base64_detect", "regex", {
                "field": "command_line", "pattern": r"[A-Za-z0-9+/]{40,}", "flags": "ignorecase",
            }),
            _make_rule(2, "c2_ip_detect", "list", {
                "field": "remote_address", "values": ["185.220.101.1"], "match_mode": "exact",
            }),
        ]

        event = _make_event(
            event_type="user_login",
            evidence={
                "user_name": "jdoe",
                "logon_type": "interactive",
                "source_ip": "10.0.0.1",
            },
            severity="info",
        )
        result = match_event(event)
        self.assertEqual(result, [])

    # ── 10. 多规则匹配 ────────────────────────────────────────────

    @patch("app.services.rule_matcher._get_candidate_rules")
    def test_multi_rule_match(self, mock_get_candidates):
        """一个事件同时命中多条规则时应返回所有匹配结果（使用旧 matcher 灰度路径确保无回归）。"""
        import app.services.rule_matcher as _rm
        _rm.USE_UNIFIED_ENGINE = False
        # 构造三条候选规则，其中两条应命中，一条不应
        mock_get_candidates.return_value = [
            _make_rule(10, "suspicious_process", "regex", {
                "field": "process_name", "pattern": r"powershell\.exe", "flags": "ignorecase",
            }),
            _make_rule(11, "encoded_cmd", "regex", {
                "field": "command_line", "pattern": r"-enc", "flags": "ignorecase",
            }),
            _make_rule(12, "c2_connection", "list", {
                "field": "remote_address", "values": ["10.0.0.99"], "match_mode": "exact",
            }),
        ]

        event = _make_event(
            event_type="process_start",
            evidence={
                "process_name": "powershell.exe",
                "command_line": "powershell.exe -enc SQBuAHYAbwBrAGUALQBXAGUAYgBSAGUAcQB1AGUAcwB0AA==",
                "remote_address": "192.168.1.1",
            },
            severity="high",
        )
        result = match_event(event)
        # 应命中两条规则（rule_id=10 和 rule_id=11），rule_id=12 不命中
        self.assertEqual(len(result), 2)
        rule_ids = {r["rule_id"] for r in result}
        self.assertIn(10, rule_ids)
        self.assertIn(11, rule_ids)
        self.assertNotIn(12, rule_ids)

        # 验证返回格式包含必要字段
        for match in result:
            self.assertIn("rule_id", match)
            self.assertIn("rule_name", match)
            self.assertIn("rule_type", match)
            self.assertIn("category", match)
            self.assertIn("severity", match)
            self.assertIn("confidence", match)
            self.assertIn("matched_fields", match)


# ===================================================================
#  辅助函数单元测试
# ===================================================================


class TestParseEvidence(unittest.TestCase):
    """_parse_evidence 辅助函数测试."""

    def test_parse_evidence_dict(self):
        """解析字典类型的 evidence。"""
        raw = {"key": "value"}
        result = _parse_evidence(raw)
        self.assertEqual(result, raw)

    def test_parse_evidence_json_string(self):
        """解析 JSON 字符串类型的 evidence。"""
        raw = '{"key": "value"}'
        result = _parse_evidence(raw)
        self.assertEqual(result, {"key": "value"})

    def test_parse_evidence_empty_string(self):
        """解析空字符串时的兜底行为。"""
        result = _parse_evidence("")
        self.assertEqual(result, {})

    def test_parse_evidence_invalid_json(self):
        """解析非法 JSON 字符串时的兜底行为。"""
        result = _parse_evidence("not-json")
        self.assertEqual(result, {})

    def test_parse_evidence_none(self):
        """解析 None 时的兜底行为。"""
        result = _parse_evidence(None)
        self.assertEqual(result, {})


class TestGetNested(unittest.TestCase):
    """_get_nested 嵌套字段读取测试."""

    def test_get_nested_top_level(self):
        """读取顶层字段。"""
        data = {"name": "powershell.exe", "pid": 1234}
        self.assertEqual(_get_nested(data, "name"), "powershell.exe")

    def test_get_nested_nested_field(self):
        """读取嵌套字段（点号分隔）。"""
        data = {"process": {"parent": {"name": "explorer.exe"}}}
        self.assertEqual(_get_nested(data, "process.parent.name"), "explorer.exe")

    def test_get_nested_missing_field(self):
        """读取不存在的字段返回 None。"""
        data = {"name": "test.exe"}
        self.assertIsNone(_get_nested(data, "non_existent"))

    def test_get_nested_partial_path(self):
        """路径中途不存在时返回 None。"""
        data = {"process": {"name": "test.exe"}}
        self.assertIsNone(_get_nested(data, "process.parent.name"))


if __name__ == "__main__":
    unittest.main()
