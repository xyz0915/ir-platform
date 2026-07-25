"""F8 护栏评估算法单元测试 — 覆盖 §7.3 四种路径。

运行：cd backend && ../venv/Scripts/python.exe -m pytest app/services/guardrail/evaluator_test.py -v
  或：cd backend && ../venv/Scripts/python.exe -m unittest app.services.guardrail.evaluator_test
"""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# 确保 backend 目录在 sys.path 中
_test_dir = os.path.dirname(os.path.abspath(__file__))
_backend_root = os.path.abspath(os.path.join(_test_dir, '..', '..', '..'))
if _backend_root not in sys.path:
    sys.path.insert(0, _backend_root)

from app.services.guardrail.evaluator import GuardrailEvaluator


# 预设 Mock 策略数据
POLICY_NO_MATCH = None  # 模拟无匹配

POLICY_WHITELIST_MATCH = {
    "policy_id": "gp-whitelist",
    "action_pattern": "host:isolate:*",
    "whitelist": '["host:isolate:web01", "host:isolate:db01"]',
    "risk_level": "high",
    "require_confirm": False,
    "rollback_plan": "",
    "enabled": True,
}

POLICY_HIGH_RISK_NO_WHITELIST = {
    "policy_id": "gp-block",
    "action_pattern": "host:isolate:*",
    "whitelist": "[]",
    "risk_level": "critical",
    "require_confirm": True,
    "rollback_plan": "",
    "enabled": True,
}

POLICY_HIGH_RISK_WITH_ROLLBACK = {
    "policy_id": "gp-rollback",
    "action_pattern": "host:isolate:*",
    "whitelist": "[]",
    "risk_level": "critical",
    "require_confirm": True,
    "rollback_plan": "孤立主机后自动恢复 ACL",
    "enabled": True,
}


class TestGuardrailEvaluate(unittest.TestCase):
    """护栏门禁评估器单元测试 — 01-api-spec.md §7.3 四种路由."""

    @patch("app.services.guardrail.evaluator.GuardrailPolicy.match_action")
    @patch("app.services.guardrail.evaluator.GuardrailHit.record")
    def test_no_policy_matched(self, mock_record, mock_match):
        """路径①：无匹配策略 → passed=true, 不记 Hit."""
        mock_match.return_value = POLICY_NO_MATCH
        result = GuardrailEvaluator.evaluate("host:query:web01")
        self.assertIsNone(result["policy_id"])
        self.assertTrue(result["passed"])
        self.assertFalse(result["whitelist_hit"])
        self.assertFalse(result["requires_confirm"])
        self.assertFalse(result["requires_rollback_plan"])
        mock_record.assert_not_called()

    @patch("app.services.guardrail.evaluator.GuardrailPolicy.match_action")
    @patch("app.services.guardrail.evaluator.GuardrailHit.record")
    def test_whitelist_hit(self, mock_record, mock_match):
        """路径②：白名单命中 → passed=true, whitelist_hit=true."""
        mock_match.return_value = POLICY_WHITELIST_MATCH
        result = GuardrailEvaluator.evaluate("host:isolate:web01")
        self.assertEqual(result["policy_id"], "gp-whitelist")
        self.assertTrue(result["whitelist_hit"])
        self.assertTrue(result["passed"])
        mock_record.assert_called_once()

    @patch("app.services.guardrail.evaluator.GuardrailPolicy.match_action")
    @patch("app.services.guardrail.evaluator.GuardrailHit.record")
    def test_high_risk_blocked(self, mock_record, mock_match):
        """路径③：高危(critical) + 无白名单 + 无预案 → passed=false (护栏拦截)."""
        mock_match.return_value = POLICY_HIGH_RISK_NO_WHITELIST
        result = GuardrailEvaluator.evaluate("host:isolate:unknown-host")
        self.assertEqual(result["policy_id"], "gp-block")
        self.assertFalse(result["whitelist_hit"])
        self.assertFalse(result["passed"])  # 拦截！
        mock_record.assert_called_once()

    @patch("app.services.guardrail.evaluator.GuardrailPolicy.match_action")
    @patch("app.services.guardrail.evaluator.GuardrailHit.record")
    def test_high_risk_with_rollback_passes(self, mock_record, mock_match):
        """路径④：高危但有回滚预案 → passed=true（即使高危）. """
        mock_match.return_value = POLICY_HIGH_RISK_WITH_ROLLBACK
        result = GuardrailEvaluator.evaluate("host:isolate:prod-srv")
        self.assertEqual(result["policy_id"], "gp-rollback")
        self.assertFalse(result["whitelist_hit"])
        self.assertTrue(result["requires_confirm"])
        self.assertTrue(result["requires_rollback_plan"])
        self.assertTrue(result["passed"])  # 有预案所以通过
        mock_record.assert_called_once()

    @patch("app.services.guardrail.evaluator.GuardrailPolicy.match_action")
    @patch("app.services.guardrail.evaluator.GuardrailHit.record")
    def test_medium_risk_passes(self, mock_record, mock_match):
        """路径⑤：中风险 + 无白名单 + 无预案 → passed=true（非高危则放行）. """
        policy = dict(POLICY_HIGH_RISK_NO_WHITELIST)
        policy["risk_level"] = "medium"
        policy["policy_id"] = "gp-medium"
        mock_match.return_value = policy
        result = GuardrailEvaluator.evaluate("host:restart:web01")
        self.assertEqual(result["policy_id"], "gp-medium")
        self.assertFalse(result["whitelist_hit"])
        self.assertTrue(result["passed"])  # 非高危 → passed
        mock_record.assert_called_once()


if __name__ == "__main__":
    unittest.main()
