#!/usr/bin/env python3
"""规则引擎威胁情报回灌单元测试（T6 验收点）.

直接写 ``threat_intel`` 表，断言 ``RuleEngine.evaluate`` 命中升级:
  - malicious → severity 升到 high 且 reason 加【威胁情报平台判黑】
  - suspicious → reason 加【威胁情报平台可疑】、severity 不变
  - 总开关 ENABLE_THREAT_INTEL_ENRICHMENT=False 时完全不加载、零影响
  - _load_iocs_by_type 未被改动（既有 list 命中 return 语义不变）
"""

import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings  # noqa: E402

TEST_DB_PATH = str(BACKEND_DIR / "data" / "test_rule_feedback.db")


class TestRuleEngineFeedback(unittest.TestCase):
    """威胁情报平台回灌升级测试."""

    @classmethod
    def setUpClass(cls):
        db_path = Path(TEST_DB_PATH)
        if db_path.exists():
            db_path.unlink()
        settings.DB_PATH = TEST_DB_PATH
        from app.database import init_db

        init_db()

    def setUp(self):
        from app.database import get_connection

        with get_connection() as conn:
            conn.execute("DELETE FROM threat_intel")
            conn.execute("DELETE FROM iocs")
        # 确保开关开启
        settings.ENABLE_THREAT_INTEL_ENRICHMENT = True

    def tearDown(self):
        settings.ENABLE_THREAT_INTEL_ENRICHMENT = True

    def _make_rule(self, ip):
        return {
            "name": "ti_feedback_rule",
            "rule_type": "list",
            "severity": "medium",
            "condition": {
                "field": "remote_address",
                "values": [ip],
                "match_mode": "exact",
            },
        }

    def _write_intel(self, ip, judgments, threat_level):
        from app.models.threat_intel import ThreatIntel

        ThreatIntel.create(
            ioc_id=None,
            ioc_type="ip",
            ioc_value=ip,
            provider="threatbook",
            risk_score=90,
            judgments=judgments,
            threat_level=threat_level,
        )

    def test_malicious_upgrades_to_high(self):
        """malicious 命中：severity 升 high + reason 含【威胁情报平台判黑】."""
        ip = "203.0.113.50"
        self._write_intel(ip, ["malicious"], "high")
        from app.rules.rule_engine import RuleEngine

        matches = RuleEngine.evaluate([{"remote_address": ip}], [self._make_rule(ip)])
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["severity"], "high")
        self.assertIn("【威胁情报平台判黑】", matches[0]["reason"])

    def test_suspicious_only_reason(self):
        """suspicious 命中：severity 不变（仍为规则 medium）+ reason 含【威胁情报平台可疑】."""
        ip = "203.0.113.51"
        self._write_intel(ip, ["suspicious"], "medium")
        from app.rules.rule_engine import RuleEngine

        matches = RuleEngine.evaluate([{"remote_address": ip}], [self._make_rule(ip)])
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["severity"], "medium")
        self.assertIn("【威胁情报平台可疑】", matches[0]["reason"])
        self.assertNotIn("【威胁情报平台判黑】", matches[0]["reason"])

    def test_switch_off_zero_impact(self):
        """总开关关闭时，即便有 malicious 记录也不升级."""
        ip = "203.0.113.52"
        self._write_intel(ip, ["malicious"], "high")
        settings.ENABLE_THREAT_INTEL_ENRICHMENT = False
        from app.rules.rule_engine import RuleEngine

        matches = RuleEngine.evaluate([{"remote_address": ip}], [self._make_rule(ip)])
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["severity"], "medium")
        self.assertNotIn("威胁情报平台", matches[0]["reason"])

    def test_clean_judgment_no_feedback(self):
        """judgments 仅 clean 时不在回灌映射中，不升级."""
        ip = "203.0.113.53"
        self._write_intel(ip, ["clean"], None)
        from app.rules.rule_engine import RuleEngine

        matches = RuleEngine.evaluate([{"remote_address": ip}], [self._make_rule(ip)])
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["severity"], "medium")
        self.assertNotIn("威胁情报平台", matches[0]["reason"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
