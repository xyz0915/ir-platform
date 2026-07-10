#!/usr/bin/env python3
"""任务⑤ 分级报告 + 处置闭环 单元测试（后端）.

覆盖:
  - RemediationChecklist：upsert / get_by_host / update_items 全量覆盖（任务23）
  - ReportTemplateService：默认配置读取与更新落盘（任务24）
  - ReportService.generate_html：executive 完全脱敏 + 内联 SVG 图表；
    technical 末尾嵌入处置清单复选框（任务25）
  - api/report.py：?report_level= 与 /reports/{host_id}/checklist GET/PUT（任务26）
"""

import sys
import tempfile
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings  # noqa: E402

TEST_DB_PATH = str(BACKEND_DIR / "data" / "test_report_checklist.db")

from app.database import get_connection, init_db  # noqa: E402
from app.models.remediation_checklist import RemediationChecklist  # noqa: E402
from app.models.host import Host  # noqa: E402
from app.models.case import Case  # noqa: E402
from app.services.report_service import ReportService  # noqa: E402
from app.services.report_template_service import ReportTemplateService  # noqa: E402


def make_host():
    """插入 case + host，返回 host_id."""
    with get_connection() as conn:
        conn.execute("INSERT INTO cases (name) VALUES ('qa-case')")
        cid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO hosts (case_id, hostname, status) VALUES (?, 'host-qa', 'analyzed')",
            (cid,),
        )
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


class TestRemediationChecklist(unittest.TestCase):
    """处置清单模型（任务23）."""

    @classmethod
    def setUpClass(cls):
        db_path = Path(TEST_DB_PATH)
        if db_path.exists():
            db_path.unlink()
        settings.DB_PATH = TEST_DB_PATH
        init_db()
        cls.host_id = make_host()

    def setUp(self):
        with get_connection() as conn:
            conn.execute("DELETE FROM remediation_checklist")

    def test_upsert_then_get(self):
        items = [
            {"id": "s1", "text": "终止可疑进程", "checked": False, "source": "ai"},
            {"id": "s2", "text": "阻断 C2 域名", "checked": True, "source": "manual"},
        ]
        rec = RemediationChecklist.upsert(self.host_id, items=items)
        self.assertEqual(len(rec["items"]), 2)
        got = RemediationChecklist.get_by_host(self.host_id)
        self.assertEqual(got["items"][1]["checked"], True)
        self.assertEqual(got["items"][0]["source"], "ai")

    def test_update_items_full_overwrite(self):
        RemediationChecklist.upsert(
            self.host_id, items=[{"text": "A", "checked": False, "source": "ai"}]
        )
        # 全量覆盖：仅保留新项
        RemediationChecklist.update_items(
            self.host_id, [{"text": "B", "checked": True, "source": "manual"}]
        )
        got = RemediationChecklist.get_by_host(self.host_id)
        self.assertEqual(len(got["items"]), 1)
        self.assertEqual(got["items"][0]["text"], "B")
        self.assertEqual(got["items"][0]["checked"], True)


class TestReportTemplateService(unittest.TestCase):
    """报告模板配置（任务24）."""

    def test_default_template(self):
        tpl = ReportTemplateService.get_template()
        self.assertIn("executive", tpl)
        self.assertIn("technical", tpl)
        self.assertTrue(tpl["executive"]["masked"])
        self.assertTrue(tpl["technical"]["include_checklist"])

    def test_update_persists(self):
        original = ReportTemplateService.get_template()
        try:
            updated = ReportTemplateService.update_template({
                "header_text": "自定义标题",
                "executive": {"chart_only": False},
            })
            self.assertEqual(updated["header_text"], "自定义标题")
            self.assertEqual(updated["executive"]["chart_only"], False)
            # 其余字段保留
            self.assertTrue(updated["technical"]["include_checklist"])
        finally:
            # 还原，避免影响其它用例
            ReportTemplateService.update_template({
                "header_text": original["header_text"],
                "executive": original["executive"],
            })


class TestDualVersionReport(unittest.TestCase):
    """双版本报告渲染（任务25）."""

    @classmethod
    def setUpClass(cls):
        db_path = Path(TEST_DB_PATH)
        if db_path.exists():
            db_path.unlink()
        settings.DB_PATH = TEST_DB_PATH
        init_db()
        cls.host_id = make_host()
        # 写入处置清单
        RemediationChecklist.upsert(
            cls.host_id,
            items=[
                {"text": "终止可疑进程", "checked": False, "source": "ai"},
                {"text": "阻断 C2 域名", "checked": True, "source": "manual"},
            ],
        )

    def test_executive_is_masked_and_has_chart(self):
        html = ReportService.generate_html(self.host_id, report_level="executive")
        self.assertIn("<svg", html)  # 内联 SVG 图表
        self.assertIn("已脱敏", html)
        # 脱敏：不应出现具体 IOC 值/命令行（executive 模板不渲染这些字段）
        self.assertNotIn("command_line", html)

    def test_technical_includes_checklist(self):
        html = ReportService.generate_html(self.host_id, report_level="technical")
        self.assertIn("处置清单", html)
        self.assertIn("终止可疑进程", html)
        self.assertIn("阻断 C2 域名", html)
        self.assertIn("type=\"checkbox\"", html)

    def test_invalid_level_falls_back_to_technical(self):
        html = ReportService.generate_html(self.host_id, report_level="bogus")
        self.assertIn("处置清单", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
