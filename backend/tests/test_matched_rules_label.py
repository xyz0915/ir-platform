"""matched_rules 中文 label 增量字段测试.

验证 AnomalyDetector 在生成 matched_rules 时，为每条命中规则增量携带
中文 `label` 字段，同时保证向后兼容：
- `name` 作为稳定 ID 永远保留、不变（统计/筛选/历史数据依赖它）。
- severity / reason 等其他字段原样保留。
- label 取值优先级：命中规则对象(rule) 的 label → 按 name 反查映射 → 兜底为 name。
"""

import unittest

from app.analysis.anomaly_detector import AnomalyDetector


class TestMatchedRulesLabel(unittest.TestCase):
    """matched_rules 携带中文 label 的单元测试."""

    def _make_match(self, rule_name, severity="high", reason="r", rule=None):
        """构造一条 RuleEngine.evaluate 风格的命中记录。"""
        match = {
            "item": {"pid": 1, "name": "x.exe", "ppid": 0, "parent_name": ""},
            "rule_name": rule_name,
            "severity": severity,
            "reason": reason,
        }
        if rule is not None:
            match["rule"] = rule
        return match

    def test_label_from_rule_object(self):
        """命中规则对象含 label 时，matched_rules 携带正确的中文 label。"""
        rule = {
            "name": "dotnet_inline_compilation",
            "label": "DotNet 内联编译执行（无文件）",
            "severity": "high",
        }
        matches = [self._make_match("dotnet_inline_compilation", severity="high", rule=rule)]
        result = AnomalyDetector._apply_accumulated_scoring(matches)
        mr = result[0]["matched_rules"][0]
        self.assertEqual(mr["name"], "dotnet_inline_compilation")  # name 稳定不变
        self.assertEqual(mr["label"], "DotNet 内联编译执行（无文件）")
        self.assertEqual(mr["severity"], "high")
        self.assertEqual(mr["reason"], "r")

    def test_label_from_rule_label_map(self):
        """无 rule 对象但传入 rule_label_map 时，按 name 反查 label。"""
        matches = [self._make_match("dotnet_inline_compilation", severity="high")]
        label_map = {"dotnet_inline_compilation": "DotNet 内联编译执行（无文件）"}
        result = AnomalyDetector._apply_accumulated_scoring(matches, rule_label_map=label_map)
        mr = result[0]["matched_rules"][0]
        self.assertEqual(mr["label"], "DotNet 内联编译执行（无文件）")
        self.assertEqual(mr["name"], "dotnet_inline_compilation")

    def test_label_fallback_to_name(self):
        """无法解析 label（无 rule 且映射缺失）时，label 兜底为 name，绝不报错。"""
        matches = [self._make_match("unknown_rule_xyz", severity="medium", reason="noreason")]
        result = AnomalyDetector._apply_accumulated_scoring(matches)
        mr = result[0]["matched_rules"][0]
        self.assertEqual(mr["label"], "unknown_rule_xyz")
        self.assertEqual(mr["name"], "unknown_rule_xyz")

    def test_all_fields_preserved(self):
        """severity / reason 等字段原样保留，仅增量加 label。"""
        rule = {"name": "r1", "label": "规则一", "severity": "critical"}
        matches = [self._make_match("r1", severity="critical", reason="boom", rule=rule)]
        result = AnomalyDetector._apply_accumulated_scoring(matches)
        mr = result[0]["matched_rules"][0]
        self.assertIn("label", mr)
        self.assertEqual(set(mr.keys()), {"name", "label", "severity", "reason"})
        self.assertEqual(mr["severity"], "critical")
        self.assertEqual(mr["reason"], "boom")

    def test_multiple_matches_each_have_label(self):
        """同一 PID 多条命中时，每条 matched_rule 均带正确 label。"""
        rules = {
            "rule_a": {"name": "rule_a", "label": "规则甲", "severity": "high"},
            "rule_b": {"name": "rule_b", "label": "规则乙", "severity": "medium"},
        }
        matches = [
            self._make_match("rule_a", severity="high", rule=rules["rule_a"]),
            self._make_match("rule_b", severity="medium", rule=rules["rule_b"]),
        ]
        result = AnomalyDetector._apply_accumulated_scoring(matches)
        mrs = result[0]["matched_rules"]
        self.assertEqual(len(mrs), 2)
        by_name = {mr["name"]: mr["label"] for mr in mrs}
        self.assertEqual(by_name["rule_a"], "规则甲")
        self.assertEqual(by_name["rule_b"], "规则乙")


if __name__ == "__main__":
    unittest.main()
