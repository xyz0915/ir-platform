"""AI 审计日志测试套件.

测试范围:
    - 创建审计日志条目
    - 分页查询
    - Token 统计聚合
    - 详情查询
"""

import os
import unittest

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

# 设置测试用数据库
TEST_DB_PATH = str(BACKEND_DIR / "data" / "test_ai_audit.db")


class TestAiAuditLog(unittest.TestCase):
    """测试 AI 审计日志功能."""

    @classmethod
    def setUpClass(cls):
        """设置测试数据库."""
        # 删除旧测试数据库
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

    def test_01_create_audit_log_success(self):
        """测试创建成功审计日志."""
        from app.services.audit_service import AuditService

        log = AuditService.log_call(
            host_id=1,
            host_name="TEST-HOST",
            profile_id=1,
            profile_name="默认配置",
            model_name="gpt-4o",
            status="success",
            prompt_tokens=500,
            completion_tokens=300,
            total_tokens=800,
            latency_ms=2500,
            masked_mode=1,
            ip_address="127.0.0.1",
        )
        self.assertIsNotNone(log)
        self.assertEqual(log["host_id"], 1)
        self.assertEqual(log["status"], "success")
        self.assertEqual(log["total_tokens"], 800)
        self.assertEqual(log["latency_ms"], 2500)
        self.assertIn("id", log)

    def test_02_create_audit_log_failed(self):
        """测试创建失败审计日志."""
        from app.services.audit_service import AuditService

        log = AuditService.log_call(
            host_id=2,
            host_name="FAILED-HOST",
            model_name="gpt-4o",
            status="failed",
            error_message="Connection timeout",
            latency_ms=30000,
        )
        self.assertEqual(log["status"], "failed")
        self.assertEqual(log["error_message"], "Connection timeout")

    def test_03_create_multiple_logs(self):
        """批量创建审计日志."""
        from app.services.audit_service import AuditService

        for i in range(5):
            AuditService.log_call(
                host_id=10 + i,
                host_name=f"HOST-{i}",
                model_name="gpt-4o",
                status="success",
                prompt_tokens=100 * (i + 1),
                completion_tokens=50 * (i + 1),
                total_tokens=150 * (i + 1),
                latency_ms=1000 * (i + 1),
            )

        # 批量查询
        result = AuditService.query_logs(page=1, page_size=10)
        # 包含之前的2条 + 5条 = 7条
        self.assertGreaterEqual(result["total"], 5)
        self.assertEqual(len(result["items"]), min(7, 10))

    def test_04_query_logs_pagination(self):
        """测试分页查询."""
        from app.services.audit_service import AuditService

        # 第1页
        page1 = AuditService.query_logs(page=1, page_size=2)
        self.assertEqual(len(page1["items"]), 2)
        self.assertEqual(page1["page"], 1)
        self.assertEqual(page1["page_size"], 2)

        # 第2页
        page2 = AuditService.query_logs(page=2, page_size=2)
        self.assertEqual(len(page2["items"]), 2)
        self.assertEqual(page2["page"], 2)

        # 两页不重叠（ID 不应相同）
        ids_p1 = {item["id"] for item in page1["items"]}
        ids_p2 = {item["id"] for item in page2["items"]}
        self.assertTrue(ids_p1.isdisjoint(ids_p2))

    def test_05_query_logs_filter_by_status(self):
        """测试按状态筛选."""
        from app.services.audit_service import AuditService

        result = AuditService.query_logs(page=1, page_size=10, status="success")
        for item in result["items"]:
            self.assertEqual(item["status"], "success")

        result_failed = AuditService.query_logs(page=1, page_size=10, status="failed")
        for item in result_failed["items"]:
            self.assertEqual(item["status"], "failed")

    def test_06_query_logs_filter_by_host(self):
        """测试按主机ID筛选."""
        from app.services.audit_service import AuditService

        result = AuditService.query_logs(page=1, page_size=10, host_id=1)
        for item in result["items"]:
            self.assertEqual(item["host_id"], 1)

    def test_07_get_detail_existing(self):
        """测试获取存在的审计日志详情."""
        from app.services.audit_service import AuditService

        # 先创建一条
        log = AuditService.log_call(
            host_id=100,
            host_name="DETAIL-HOST",
            model_name="gpt-4o",
            status="success",
            total_tokens=1000,
            latency_ms=5000,
        )
        # 查询详情
        detail = AuditService.get_detail(log["id"])
        self.assertEqual(detail["id"], log["id"])
        self.assertEqual(detail["host_id"], 100)

    def test_08_get_detail_nonexistent(self):
        """测试获取不存在的审计日志详情."""
        from app.services.audit_service import AuditService

        with self.assertRaises(ValueError) as ctx:
            AuditService.get_detail(99999)
        self.assertIn("不存在", str(ctx.exception))

    def test_09_get_token_stats(self):
        """测试 Token 使用统计."""
        from app.services.audit_service import AuditService

        stats = AuditService.get_token_stats()
        self.assertIn("total_prompt_tokens", stats)
        self.assertIn("total_completion_tokens", stats)
        self.assertIn("total_tokens", stats)
        self.assertIn("total_calls", stats)
        self.assertIn("success_calls", stats)
        self.assertIn("failed_calls", stats)
        self.assertIn("avg_latency_ms", stats)
        self.assertIn("total_cost_estimate", stats)
        self.assertGreaterEqual(stats["total_calls"], 7)

    def test_10_get_token_summary_daily(self):
        """测试按日汇总."""
        from app.services.audit_service import AuditService

        summary = AuditService.get_token_summary(group_by="daily")
        self.assertIsInstance(summary, list)

    def test_11_get_token_summary_model(self):
        """测试按模型汇总."""
        from app.services.audit_service import AuditService

        summary = AuditService.get_token_summary(group_by="model")
        self.assertIsInstance(summary, list)
        if summary:
            self.assertIn("model_name", summary[0])

    def test_12_get_token_summary_profile(self):
        """测试按 Profile 汇总."""
        from app.services.audit_service import AuditService

        summary = AuditService.get_token_summary(group_by="profile")
        self.assertIsInstance(summary, list)
        if summary:
            self.assertIn("profile_name", summary[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
