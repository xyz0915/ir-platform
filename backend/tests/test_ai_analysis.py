"""AI分析报告版本管理测试套件.

测试范围:
    - AiAnalysisReport 版本递增 (v1 -> v2 -> v3)
    - is_latest 标记切换
    - 版本列表查询
    - 按版本号查询
"""

import os
import unittest

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

TEST_DB_PATH = str(BACKEND_DIR / "data" / "test_ai_analysis.db")


class TestAiAnalysisReportVersioning(unittest.TestCase):
    """测试 AI 分析报告版本管理."""

    @classmethod
    def setUpClass(cls):
        """设置测试数据库并创建必要的基础数据."""
        db_path = Path(TEST_DB_PATH)
        if db_path.exists():
            db_path.unlink()

        from app.config import settings
        settings.DB_PATH = TEST_DB_PATH

        Path(settings.DATA_DIR).mkdir(parents=True, exist_ok=True)
        Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
        Path(settings.AGENT_DIR).mkdir(parents=True, exist_ok=True)

        from app.database import init_db
        init_db()

        # 创建案件和主机（admin用户由init_db自动创建）
        from app.database import get_connection
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO cases (name, case_number) VALUES (?, ?)",
                ("版本测试案件", "VER-TEST-001"),
            )
            conn.execute(
                "INSERT INTO hosts (case_id, hostname, ip_address, os_type, status) VALUES (?, ?, ?, ?, ?)",
                (1, "VER-HOST", "10.0.0.5", "windows", "imported"),
            )

    def test_01_create_first_report_v1(self):
        """创建第一个报告应为 v1，is_latest=1."""
        from app.models.ai_analysis import AiAnalysisReport

        report = AiAnalysisReport.create(
            host_id=1,
            case_id=1,
            risk_assessment="risk v1",
            threat_analysis="threat v1",
            timeline_analysis="timeline v1",
            recommendations="rec v1",
            raw_response="raw v1",
            model_used="gpt-4o",
            tokens_used=500,
            profile_id=1,
            masked_mode=1,
        )
        self.assertEqual(report["version"], 1)
        self.assertEqual(report["is_latest"], 1)
        self.assertEqual(report["host_id"], 1)

    def test_02_create_second_report_v2(self):
        """创建第二个报告应为 v2，旧报告 is_latest=0."""
        from app.models.ai_analysis import AiAnalysisReport

        report = AiAnalysisReport.create(
            host_id=1,
            case_id=1,
            risk_assessment="risk v2",
            threat_analysis="threat v2",
            timeline_analysis="timeline v2",
            recommendations="rec v2",
            raw_response="raw v2",
            model_used="gpt-4o",
            tokens_used=600,
            profile_id=1,
            masked_mode=0,
        )
        self.assertEqual(report["version"], 2)
        self.assertEqual(report["is_latest"], 1)

        # 旧报告应不再是最新
        old_report = AiAnalysisReport.get_by_id(1)
        self.assertEqual(old_report["is_latest"], 0)

    def test_03_create_third_report_v3(self):
        """创建第三个报告应为 v3."""
        from app.models.ai_analysis import AiAnalysisReport

        report = AiAnalysisReport.create(
            host_id=1,
            case_id=1,
            risk_assessment="risk v3",
            model_used="gpt-4o-mini",
            tokens_used=300,
            prompt_tokens=200,
            completion_tokens=100,
        )
        self.assertEqual(report["version"], 3)
        self.assertEqual(report["is_latest"], 1)

        # 所有旧报告 is_latest=0
        r1 = AiAnalysisReport.get_by_id(1)
        r2 = AiAnalysisReport.get_by_id(2)
        self.assertEqual(r1["is_latest"], 0)
        self.assertEqual(r2["is_latest"], 0)

    def test_04_get_by_host_returns_latest(self):
        """get_by_host 应返回 is_latest=1 的报告."""
        from app.models.ai_analysis import AiAnalysisReport

        report = AiAnalysisReport.get_by_host(1)
        self.assertIsNotNone(report)
        self.assertEqual(report["is_latest"], 1)
        self.assertEqual(report["version"], 3)

    def test_05_list_versions(self):
        """list_versions 应返回所有版本（按 version DESC 排序）."""
        from app.models.ai_analysis import AiAnalysisReport

        versions = AiAnalysisReport.list_versions(1)
        self.assertEqual(len(versions), 3)
        # 按 version DESC
        self.assertEqual(versions[0]["version"], 3)
        self.assertEqual(versions[1]["version"], 2)
        self.assertEqual(versions[2]["version"], 1)
        # 只有最新的 is_latest=1
        self.assertEqual(versions[0]["is_latest"], 1)
        self.assertEqual(versions[1]["is_latest"], 0)
        self.assertEqual(versions[2]["is_latest"], 0)

    def test_06_get_by_version(self):
        """get_by_version 应返回指定版本报告."""
        from app.models.ai_analysis import AiAnalysisReport

        report = AiAnalysisReport.get_by_version(1, 1)
        self.assertIsNotNone(report)
        self.assertEqual(report["version"], 1)
        self.assertEqual(report["risk_assessment"], "risk v1")

        report2 = AiAnalysisReport.get_by_version(1, 3)
        self.assertEqual(report2["version"], 3)

    def test_07_get_by_version_nonexistent(self):
        """查询不存在的版本应返回 None."""
        from app.models.ai_analysis import AiAnalysisReport

        report = AiAnalysisReport.get_by_version(1, 99)
        self.assertIsNone(report)

    def test_08_list_versions_empty_host(self):
        """无报告的主机返回空列表."""
        from app.models.ai_analysis import AiAnalysisReport

        versions = AiAnalysisReport.list_versions(999)
        self.assertEqual(len(versions), 0)

    def test_09_delete_by_host(self):
        """删除主机的所有报告."""
        from app.models.ai_analysis import AiAnalysisReport
        from app.database import get_connection

        # 确认有报告
        self.assertIsNotNone(AiAnalysisReport.get_by_host(1))

        # 删除
        AiAnalysisReport.delete_by_host(1)

        # 确认已删除
        self.assertIsNone(AiAnalysisReport.get_by_host(1))
        self.assertEqual(len(AiAnalysisReport.list_versions(1)), 0)

    def test_10_get_by_host_no_report(self):
        """无报告的主机应返回 None."""
        from app.models.ai_analysis import AiAnalysisReport

        # 已在上个测试中删除
        report = AiAnalysisReport.get_by_host(1)
        self.assertIsNone(report)

    def test_11_token_fields_preserved(self):
        """验证 prompt_tokens 和 completion_tokens 字段."""
        from app.models.ai_analysis import AiAnalysisReport

        # 重新创建报告
        report = AiAnalysisReport.create(
            host_id=1,
            case_id=1,
            risk_assessment="token test",
            model_used="gpt-4o",
            tokens_used=1000,
            prompt_tokens=600,
            completion_tokens=400,
        )
        self.assertEqual(report["prompt_tokens"], 600)
        self.assertEqual(report["completion_tokens"], 400)

    def test_12_export_for_pdf(self):
        """测试 export_for_pdf 包含主机信息."""
        from app.models.ai_analysis import AiAnalysisReport

        report = AiAnalysisReport.get_by_host(1)
        export = AiAnalysisReport.export_for_pdf(report["id"])
        self.assertIsNotNone(export)
        self.assertIn("hostname", export)
        self.assertEqual(export["hostname"], "VER-HOST")


if __name__ == "__main__":
    unittest.main(verbosity=2)
