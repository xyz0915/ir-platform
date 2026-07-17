"""EVENT_TYPE_MAP 扩展测试（v2 §4.1）"""
from __future__ import annotations

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestEventTypeMap(unittest.TestCase):
    """验证 import_service 中的 EVENT_TYPE_MAP 包含全部期待区块。"""

    def test_all_new_blocks_in_map(self):
        from app.services.import_service import ImportService
        # 读取 import_json 函数源码中的 EVENT_TYPE_MAP
        import inspect
        source = inspect.getsource(ImportService.import_json)
        # 检查前缀块是否存在
        expected = [
            "processes", "network_connections", "registry_keys",
            "file_hashes", "files", "logs", "security",
            "browser", "usb", "remote_control", "ioc",
            "persistence_items", "wmi_subscriptions", "startup_items",
            "services", "users", "network_interfaces",
        ]
        for block in expected:
            self.assertIn(block, source, f"EVENT_TYPE_MAP 缺少 {block}")

    def test_new_event_types_in_frontend_category_map(self):
        from app.services.frontend_projection import EVENT_TYPE_TO_CATEGORY
        self.assertIn("file_event", EVENT_TYPE_TO_CATEGORY)
        self.assertIn("log_event", EVENT_TYPE_TO_CATEGORY)
        self.assertIn("security_event", EVENT_TYPE_TO_CATEGORY)
        self.assertIn("browser_event", EVENT_TYPE_TO_CATEGORY)
        self.assertIn("usb_event", EVENT_TYPE_TO_CATEGORY)
        self.assertIn("remote_control_event", EVENT_TYPE_TO_CATEGORY)
        self.assertIn("ioc_event", EVENT_TYPE_TO_CATEGORY)
        self.assertEqual(EVENT_TYPE_TO_CATEGORY["file_event"], "execution")
        self.assertEqual(EVENT_TYPE_TO_CATEGORY["ioc_event"], "ioc")

    def test_ac_mapped_blocks_in_dq_monitor(self):
        from app.services.dq_monitor import AC_MAPPED_BLOCKS
        self.assertIn("files", AC_MAPPED_BLOCKS)
        self.assertIn("logs", AC_MAPPED_BLOCKS)
        self.assertIn("security", AC_MAPPED_BLOCKS)
        self.assertIn("browser", AC_MAPPED_BLOCKS)
        self.assertIn("usb", AC_MAPPED_BLOCKS)
        self.assertIn("remote_control", AC_MAPPED_BLOCKS)
        self.assertIn("ioc", AC_MAPPED_BLOCKS)

    def test_dq_coverage_recognizes_new_blocks(self):
        from app.services.dq_monitor import EXPECTED_RAW_BLOCKS
        for b in ["files", "logs", "security", "browser", "usb", "remote_control", "ioc"]:
            self.assertIn(b, EXPECTED_RAW_BLOCKS)

    def test_frontend_projection_v2_1_field_count(self):
        from app.services.frontend_projection import REQUIRED_FIELDS, AUXILIARY_FIELDS
        self.assertEqual(len(REQUIRED_FIELDS), 14, "§10.1 必填封顶 14")
        self.assertEqual(len(AUXILIARY_FIELDS), 9, "§10.2 辅助 9 项")


if __name__ == "__main__":
    unittest.main()
