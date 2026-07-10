#!/usr/bin/env python3
"""AI 全貌分析 / 处置建议（任务②）单元测试.

覆盖：
  - AIMode 枚举含 overview / remediation
  - PromptBuilder.build_overview / build_remediation 返回合法 system_prompt / user_prompt
  - AiAnalysisReport.create 接受 ai_payload 并持久化，get_by_version 可回读
  - _enrich_report 类场景下 ai_payload 可被解析（模型层验证）
"""

import json
import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings  # noqa: E402
from app.shared.ai_constants import AIMode  # noqa: E402
from app.services.prompt_builder import (  # noqa: E402
    PromptBuilder, OVERVIEW_SYSTEM_PROMPT, REMEDIATION_SYSTEM_PROMPT,
)

TEST_DB_PATH = str(BACKEND_DIR / "data" / "test_ai_overview.db")


class TestAIModeEnum(unittest.TestCase):
    def test_overview_remediation_present(self):
        self.assertIn("overview", AIMode.values())
        self.assertIn("remediation", AIMode.values())
        self.assertEqual(AIMode.OVERVIEW.value, "overview")
        self.assertEqual(AIMode.REMEDIATION.value, "remediation")


class TestPromptBuilderOverviewRemediation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db_path = Path(TEST_DB_PATH)
        if db_path.exists():
            db_path.unlink()
        settings.DB_PATH = TEST_DB_PATH
        from app.database import init_db
        init_db()
        from app.models.host import Host
        from app.models.analysis import AnalysisResult
        from app.models.case import Case

        case = Case.create(name="test-case")
        cls.case_id = case["id"]
        host = Host.create(case_id=cls.case_id, hostname="web01", ip_address="10.0.0.5",
                           os_type="Windows", os_version="10")
        cls.host_id = host["id"]
        AnalysisResult.create_or_replace(
            host_id=cls.host_id, risk_level="high", risk_score=80,
            total_findings=3, summary="发现可疑 powershell 与 C2 外连", details={},
        )

    def test_build_overview(self):
        out = PromptBuilder.build_overview(self.host_id)
        self.assertIn("system_prompt", out)
        self.assertIn("user_prompt", out)
        self.assertEqual(out["system_prompt"], OVERVIEW_SYSTEM_PROMPT.strip())
        self.assertIn("story_line", out["user_prompt"])
        self.assertIn("web01", out["user_prompt"])

    def test_build_remediation(self):
        out = PromptBuilder.build_remediation(self.host_id)
        self.assertEqual(out["system_prompt"], REMEDIATION_SYSTEM_PROMPT.strip())
        self.assertIn("remediation_scripts", out["user_prompt"])

    def test_build_overview_masked(self):
        out = PromptBuilder.build_overview(self.host_id, masked=True)
        # 脱敏后 IP 不应再以明文完整出现（10.0.0.5 -> 10.0.*.*)
        self.assertNotIn("10.0.0.5", out["user_prompt"])


class TestAiReportPayload(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db_path = Path(TEST_DB_PATH)
        if db_path.exists():
            db_path.unlink()
        settings.DB_PATH = TEST_DB_PATH
        from app.database import init_db
        init_db()
        from app.models.host import Host
        from app.models.case import Case

        case = Case.create(name="test-case-2")
        host = Host.create(case_id=case["id"], hostname="web02", ip_address="10.0.0.6")
        cls.host_id = host["id"]

    def test_overview_payload_stored_and_readable(self):
        from app.models.ai_analysis import AiAnalysisReport

        payload = {
            "mode": "overview",
            "story_line": "攻击者于 10:02 钓鱼投递 loader…",
            "key_events": [{"time": "2026-07-11 10:05", "dimension": "process",
                            "summary": "powershell -enc"}],
        }
        report = AiAnalysisReport.create(
            host_id=self.host_id, case_id=1,
            risk_assessment=json.dumps({}), threat_analysis=json.dumps({}),
            timeline_analysis=json.dumps({}), recommendations=json.dumps({}),
            raw_response="{}", model_used="test-model", tokens_used=10,
            analysis_type="overview", ai_payload=json.dumps(payload, ensure_ascii=False),
        )
        self.assertIsNotNone(report.get("id"))

        # get_by_id 回读 ai_payload
        fetched = AiAnalysisReport.get_by_id(report["id"])
        self.assertEqual(fetched["analysis_type"], "overview")
        self.assertEqual(json.loads(fetched["ai_payload"])["story_line"],
                         payload["story_line"])

        # get_by_host（is_latest）可查
        latest = AiAnalysisReport.get_by_host(self.host_id)
        self.assertEqual(latest["id"], report["id"])
        # get_by_version 可查
        by_ver = AiAnalysisReport.get_by_version(self.host_id, report["version"])
        self.assertEqual(by_ver["id"], report["id"])

    def test_remediation_payload_stored(self):
        from app.models.ai_analysis import AiAnalysisReport

        payload = {
            "mode": "remediation",
            "remediation_scripts": [{
                "id": "step-1", "description": "终止进程", "language": "powershell",
                "script": "Stop-Process", "risk": "medium", "reversible": True,
                "requires_approval": True,
            }],
        }
        report = AiAnalysisReport.create(
            host_id=self.host_id, case_id=1,
            risk_assessment=json.dumps({}), threat_analysis=json.dumps({}),
            timeline_analysis=json.dumps({}), recommendations=json.dumps({}),
            raw_response="{}", model_used="test-model", tokens_used=10,
            analysis_type="remediation", ai_payload=json.dumps(payload, ensure_ascii=False),
        )
        fetched = AiAnalysisReport.get_by_id(report["id"])
        self.assertEqual(
            json.loads(fetched["ai_payload"])["remediation_scripts"][0]["id"], "step-1"
        )


if __name__ == "__main__":
    unittest.main()
