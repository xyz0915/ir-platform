#!/usr/bin/env python3
"""v1.3.0「AI 分析作战化」单元测试.

覆盖解析层统一守护（R1-1/R1-2/R3-3/R4-1/R5）、ai_service 委托（T17）、
RuleEngine 攻击链封装（T20）、R2-3 只读派发红线（T12）。
所有用例不依赖网络与真实采集器，DB 相关用例以 mock 隔离。
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.services.ai_parse_guard import normalize_and_guard  # noqa: E402
from app.services.attack_technique_service import AttackTechniqueService  # noqa: E402
from app.services.ai_service import AiService  # noqa: E402
from app.rules.rule_engine import RuleEngine  # noqa: E402


class TestGuardScoreBreakdown(unittest.TestCase):
    """R1-2：risk_score == sum(score_breakdown)，不符以 breakdown 为准重算。"""

    def test_recomputes_risk_score_from_breakdown(self):
        parsed = {
            "risk_assessment": {
                "risk_level": "高",
                "risk_score": 999,  # 故意与 breakdown 不符
                "score_breakdown": [
                    {"signal": "malicious_behavior", "contribution": 30, "evidence": "x"},
                    {"signal": "persistence", "contribution": 15, "evidence": "y"},
                ],
            }
        }
        g = normalize_and_guard(parsed)
        self.assertEqual(g["risk_assessment"]["risk_score"], 45)
        self.assertTrue(
            any(c["rule"] == "R1-2" for c in g["risk_assessment"]["consistency_corrections"])
        )

    def test_keeps_declared_score_when_consistent(self):
        parsed = {
            "risk_assessment": {
                "risk_level": "高",
                "risk_score": 45,
                "score_breakdown": [
                    {"signal": "malicious_behavior", "contribution": 30, "evidence": "x"},
                    {"signal": "persistence", "contribution": 15, "evidence": "y"},
                ],
            }
        }
        g = normalize_and_guard(parsed)
        self.assertEqual(g["risk_assessment"]["risk_score"], 45)


class TestGuardNormalThreatCap(unittest.TestCase):
    """R1-1：threat_type=正常 且无恶意行为时，risk_level 不得高于「中」。"""

    def test_caps_high_level_to_mid(self):
        parsed = {
            "risk_assessment": {
                "threat_type": "正常",
                "risk_level": "高危",
                "score_breakdown": [],
            },
            "threat_analysis": {"malicious_behaviors": []},
        }
        g = normalize_and_guard(parsed)
        self.assertEqual(g["risk_assessment"]["risk_level"], "中")
        self.assertIn("reason", g["risk_assessment"])


class TestGuardBaselinePenalty(unittest.TestCase):
    """R3-3：historical_known=true 的 score_breakdown 项按 BASELINE_PENALTY 回落。"""

    def test_penalty_applied_to_known_item(self):
        parsed = {
            "risk_assessment": {
                "risk_level": "高",
                "risk_score": 45,
                "score_breakdown": [
                    {"signal": "malicious_behavior", "contribution": 30, "evidence": "新发现", "historical_known": False},
                    {"signal": "persistence", "contribution": 30, "evidence": "基线已知", "historical_known": True},
                ],
            }
        }
        g = normalize_and_guard(parsed, baseline={"known_items": {}})
        ra = g["risk_assessment"]
        # 基线已知项 30 -> 15，新项保持 30，合计 45
        self.assertEqual(ra["risk_score"], 45)
        known = next(x for x in ra["score_breakdown"] if x["signal"] == "persistence")
        self.assertEqual(known["contribution"], 15)
        self.assertTrue(any(c["rule"] == "R3-3" for c in ra["consistency_corrections"]))


class TestGuardRareHighSignals(unittest.TestCase):
    """R5：命中 RARE_HIGH_SIGNALS 强制 P0 + escalation_conditions。"""

    def test_rare_signal_escalates(self):
        parsed = {
            "risk_assessment": {"risk_level": "中"},
            "threat_analysis": {
                "malicious_behaviors": [
                    {"name": "检测到 fileless_powershell 执行"}
                ]
            },
        }
        g = normalize_and_guard(parsed)
        signals = [r["signal"] for r in g["rare_high_signals"]]
        self.assertIn("fileless_powershell", signals)
        self.assertTrue(any("fileless_powershell" in (c.get("condition") or "") for c in g["escalation_conditions"]))


class TestGuardMitreResolve(unittest.TestCase):
    """R4-1：mitre_attack 经覆盖库查表，未知标「待确认」。"""

    def test_resolves_known_and_unknown(self):
        parsed = {
            "risk_assessment": {
                "mitre_attack": ["T1059.001", "T9999.999"],
            }
        }
        g = normalize_and_guard(parsed)
        techs = {t["id"]: t for t in g["mitre_attack"]}
        self.assertIn("T1059.001", techs)
        self.assertEqual(techs["T1059.001"]["name"], "PowerShell")  # 覆盖库内置
        self.assertEqual(techs["T9999.999"]["name"], "待确认")
        self.assertFalse(techs["T9999.999"]["known"])

    def test_coverage_file_loads(self):
        cov = AttackTechniqueService._load_coverage()
        self.assertIn("techniques", cov)
        self.assertIn("T1059.001", cov["techniques"])


class TestAiServiceGuardDelegation(unittest.TestCase):
    """T17：ai_service.parse_json_response 委托守护且保留 timeline_analysis。"""

    def test_timeline_preserved(self):
        content = (
            '{"risk_assessment": {"risk_level": "高", "score_breakdown": []},'
            '"threat_analysis": {}, "timeline_analysis": {"events": [1,2,3]},'
            '"recommendations": {}}'
        )
        parsed = AiService.parse_json_response(content)
        self.assertIn("timeline_analysis", parsed)
        self.assertEqual(parsed["timeline_analysis"], {"events": [1, 2, 3]})
        # 守护注入的新字段存在
        self.assertIn("audience", parsed)
        self.assertIn("mitre_attack", parsed)


class TestRuleEngineAttackChain(unittest.TestCase):
    """T20：RuleEngine.get_attack_chain_hits 读取 details.attack_chains。"""

    def test_reads_attack_chains(self):
        fake = {
            "details": {
                "attack_chains": [
                    {"rule_name": "勒索链", "severity": "critical", "reason": "x", "steps": []}
                ]
            }
        }
        with mock.patch(
            "app.models.analysis.AnalysisResult.get_by_host", return_value=fake
        ):
            hits = RuleEngine.get_attack_chain_hits(1)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["rule_name"], "勒索链")

    def test_empty_when_no_details(self):
        with mock.patch(
            "app.models.analysis.AnalysisResult.get_by_host",
            return_value={"details": {}},
        ):
            self.assertEqual(RuleEngine.get_attack_chain_hits(1), [])


class TestDispatchRedLine(unittest.TestCase):
    """T12：R2-3 派发红线——非只读/危险命令一律拒绝。"""

    def test_rejects_non_auto_runnable(self):
        import asyncio

        from app.services.dispatch_service import DispatchService

        # 通过公开接口验证：auto_runnable=False 必须拒绝（绝不自动处置）
        with self.assertRaises(ValueError):
            asyncio.run(
                DispatchService.dispatch_readonly(
                    1, "manual_review", "x", "echo hi", auto_runnable=False
                )
            )

    def test_rejects_dangerous_command(self):
        from app.services.dispatch_service import DispatchService

        with self.assertRaises(ValueError):
            DispatchService._reject_dangerous("powershell -c 'Remove-Item C:\\\\temp -Force'")

    def test_allows_safe_readonly(self):
        from app.services.dispatch_service import DispatchService

        # 仅做静态拒绝校验，不真正执行子进程
        try:
            DispatchService._reject_dangerous("powershell -c 'Get-CimInstance Win32_StartupCommand'")
        except ValueError:
            self.fail("安全只读命令不应被拒绝")


if __name__ == "__main__":
    unittest.main()
