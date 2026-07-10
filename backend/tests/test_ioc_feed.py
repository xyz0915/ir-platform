#!/usr/bin/env python3
"""外部威胁源（MISP / STIX / CSV）拉取脚本的单元测试.

测试目标:
  - 三个解析器（CSV / MISP / STIX）正确性，使用内联 mock 文本/json，不发起真实网络请求。
  - 字段映射正确性（ip / domain / url / hash / cert）。
  - 灌表集成：归一化列表调 ``Ioc.batch_create``，断言入库条数与去重生效。
  - CSV 缺列 / 空值跳过不报错。

复用约定（与 test_ioc_engine.py 一致）:
  - 使用独立测试库（data/test_ioc_feed.db），setUpClass 调用 init_db() 建表并种子。
  - setUp 清空 iocs 表，保证用例间隔离。
  - 不修改任何既有业务检测逻辑，只验证新增脚本/模型写入入口的正确性。
"""

import json
import sys
import unittest
from pathlib import Path

# 确保 backend 目录在 Python 路径中（与仓库内其它测试一致）
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))
# 脚本目录加入路径，便于直接 import ioc_feed_sync 模块
SCRIPTS_DIR = BACKEND_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import ioc_feed_sync  # noqa: E402
from app.config import settings  # noqa: E402
from app.models.ioc import Ioc  # noqa: E402

# 独立测试库，避免污染开发/基线库
TEST_DB_PATH = str(BACKEND_DIR / "data" / "test_ioc_feed.db")


class IocFeedTestCase(unittest.TestCase):
    """所有测试的统一基类：隔离测试库 + 用例间清空 iocs 表."""

    @classmethod
    def setUpClass(cls):
        """初始化独立测试库并载入默认规则/IOC 种子."""
        db_path = Path(TEST_DB_PATH)
        if db_path.exists():
            db_path.unlink()

        settings.DB_PATH = TEST_DB_PATH

        from app.database import init_db

        init_db()

    def setUp(self):
        """每个用例前清空 iocs 表，保证互相隔离."""
        for it in Ioc.list():
            Ioc.delete(it["id"])


class TestParseCsv(IocFeedTestCase):
    """CSV 解析器测试."""

    def test_type_value_columns_with_type_map(self):
        """type/value 列 + type_map 映射（含 sha256->hash）."""
        csv_text = "type,value\nip,1.2.3.4\ndomain,evil.com\nsha256,abcde123\n"
        items = ioc_feed_sync.parse_csv(
            csv_text,
            {"ip": "ip", "domain": "domain", "url": "url", "sha256": "hash"},
            "abuse-ch-csv",
        )
        self.assertEqual(len(items), 3)
        by_type = {it["ioc_type"]: it["ioc_value"] for it in items}
        self.assertEqual(by_type["ip"], "1.2.3.4")
        self.assertEqual(by_type["domain"], "evil.com")
        self.assertEqual(by_type["hash"], "abcde123")
        # 全部标注 source 便于溯源
        self.assertTrue(all(it["source"] == "abuse-ch-csv" for it in items))

    def test_ioc_type_ioc_value_columns(self):
        """ioc_type/ioc_value 列（已为系统类型）直接采用，并带 description."""
        csv_text = "ioc_type,ioc_value,description\nurl,http://x/y,C2 url\n"
        items = ioc_feed_sync.parse_csv(csv_text, None, "feed-x")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["ioc_type"], "url")
        self.assertEqual(items[0]["ioc_value"], "http://x/y")
        self.assertEqual(items[0]["description"], "C2 url")
        self.assertEqual(items[0]["source"], "feed-x")

    def test_skips_empty_and_missing_value(self):
        """空行 / 缺值行应被跳过，不报错."""
        csv_text = "type,value\nip,1.1.1.1\n,\nip,\ndomain,evil2.com\n"
        items = ioc_feed_sync.parse_csv(csv_text, None, "feed")
        # 仅 1.1.1.1 与 evil2.com 应保留（空行与空值行跳过）
        self.assertEqual(len(items), 2)
        values = {it["ioc_value"] for it in items}
        self.assertIn("1.1.1.1", values)
        self.assertIn("evil2.com", values)
        self.assertNotIn("", values)

    def test_skips_unknown_type(self):
        """无法映射为合法 ioc_type 的行应被跳过."""
        csv_text = "type,value\nweirdtype,foo\nip,2.2.2.2\n"
        items = ioc_feed_sync.parse_csv(csv_text, None, "feed")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["ioc_value"], "2.2.2.2")
        self.assertEqual(items[0]["ioc_type"], "ip")

    def test_empty_input(self):
        """空文本 / 仅表头不抛异常，返回空列表."""
        self.assertEqual(ioc_feed_sync.parse_csv("", None, "feed"), [])
        self.assertEqual(
            ioc_feed_sync.parse_csv("type,value\n", None, "feed"), []
        )


class TestParseMisp(IocFeedTestCase):
    """MISP 解析器测试."""

    def test_event_attribute_mapping(self):
        """Event/Attribute 各类型映射 + 空值/未知类型跳过."""
        payload = {
            "Event": [
                {
                    "Attribute": [
                        {"type": "ip-dst", "value": "8.8.8.8", "comment": "dns"},
                        {"type": "ip-src", "value": "9.9.9.9"},
                        {"type": "domain", "value": "evil.com"},
                        {"type": "url", "value": "http://evil.com/x"},
                        {"type": "sha256", "value": "deadbeef"},
                        {"type": "md5", "value": "abc123"},
                        {"type": "x509-certificate", "value": "CERTDATA"},
                        {"type": "some-unknown", "value": "zzz"},
                        {"type": "domain", "value": ""},
                    ]
                }
            ]
        }
        items = ioc_feed_sync.parse_misp(payload, "misp-intel")
        by_value = {it["ioc_value"]: it["ioc_type"] for it in items}
        self.assertEqual(by_value["8.8.8.8"], "ip")
        self.assertEqual(by_value["9.9.9.9"], "ip")
        self.assertEqual(by_value["evil.com"], "domain")
        self.assertEqual(by_value["http://evil.com/x"], "url")
        self.assertEqual(by_value["deadbeef"], "hash")
        self.assertEqual(by_value["abc123"], "hash")
        self.assertEqual(by_value["CERTDATA"], "cert")
        # 未知类型与空值被跳过
        self.assertNotIn("zzz", by_value)
        self.assertNotIn("", by_value)
        self.assertEqual(len(items), 7)
        self.assertEqual(items[0]["source"], "misp-intel")
        # comment 作为 description
        self.assertEqual(items[0]["description"], "dns")


class TestParseStix(IocFeedTestCase):
    """STIX 2.x 解析器测试（内置正则提取 indicator pattern）."""

    def test_indicator_pattern_extraction(self):
        """indicator pattern 提取值并映射各类型；非 indicator 对象跳过."""
        bundle = {
            "objects": [
                {"type": "indicator", "pattern": "[ip-addr:value = '198.51.100.1']"},
                {
                    "type": "indicator",
                    "pattern": "[domain-name:value = 'evil.io']",
                    "name": "C2",
                },
                {"type": "indicator", "pattern": "[url:value = 'https://evil.io/p']"},
                {"type": "indicator", "pattern": "[file:hashes.'SHA-256' = 'AAAABBBB']"},
                {"type": "indicator", "pattern": "[file:hashes.SHA-256 = 'CCCC']"},
                {
                    "type": "indicator",
                    "pattern": "[x509-certificate:subject = 'CN=evil']",
                },
                {"type": "malware", "name": "not-indicator"},  # 跳过
                {"type": "indicator", "pattern": "[]"},  # 无匹配跳过
            ]
        }
        items = ioc_feed_sync.parse_stix(bundle, "stix-bundle")
        by_value = {it["ioc_value"]: it["ioc_type"] for it in items}
        self.assertEqual(by_value["198.51.100.1"], "ip")
        self.assertEqual(by_value["evil.io"], "domain")
        self.assertEqual(by_value["https://evil.io/p"], "url")
        self.assertEqual(by_value["AAAABBBB"], "hash")
        self.assertEqual(by_value["CCCC"], "hash")
        self.assertEqual(by_value["CN=evil"], "cert")
        self.assertEqual(len(items), 6)
        self.assertEqual(items[0]["source"], "stix-bundle")


class TestIocBatchCreateDedup(IocFeedTestCase):
    """灌表集成：batch_create 入库与去重."""

    def test_inserts_and_dedups(self):
        """重复 (ioc_type, ioc_value) 只保留一条."""
        items = [
            {"ioc_type": "ip", "ioc_value": "1.1.1.1", "source": "feed"},
            {"ioc_type": "ip", "ioc_value": "1.1.1.1", "source": "feed"},  # 重复
            {"ioc_type": "domain", "ioc_value": "a.com", "source": "feed"},
            {"ioc_type": "hash", "ioc_value": "dead", "source": "feed"},
        ]
        inserted = Ioc.batch_create(items)
        self.assertEqual(inserted, 3)
        all_iocs = Ioc.list()
        self.assertEqual(len(all_iocs), 3)
        ips = [i for i in all_iocs if i["ioc_type"] == "ip"]
        self.assertEqual(len(ips), 1)

    def test_skips_empty_fields(self):
        """空 ioc_type / 空 ioc_value 的项被跳过."""
        items = [
            {"ioc_type": "", "ioc_value": "x"},
            {"ioc_type": "ip", "ioc_value": ""},
            {"ioc_type": "url", "ioc_value": "http://ok"},
        ]
        inserted = Ioc.batch_create(items)
        self.assertEqual(inserted, 1)
        self.assertEqual(len(Ioc.list()), 1)


class TestPipeline(IocFeedTestCase):
    """端到端：解析器 -> 归一化 -> 灌表."""

    def test_csv_to_db_with_source_and_enabled(self):
        """CSV 解析结果灌表后，source 标注 feed 名、默认 enabled=1."""
        csv_text = "type,value\nip,5.5.5.5\nurl,http://5.5.5.5/x\n"
        items = ioc_feed_sync.parse_csv(
            csv_text, {"ip": "ip", "url": "url"}, "abuse-ch-csv"
        )
        inserted = Ioc.batch_create(items)
        self.assertEqual(inserted, 2)
        stored = Ioc.list()
        self.assertEqual(len(stored), 2)
        for it in stored:
            self.assertEqual(it["source"], "abuse-ch-csv")
            self.assertTrue(it["enabled"])

    def test_misp_to_db_dedup_across_runs(self):
        """同 feed 两次灌表，去重保证最终只保留一份."""
        payload = {
            "Event": [
                {"Attribute": [{"type": "ip-dst", "value": "7.7.7.7"}]}
            ]
        }
        items = ioc_feed_sync.parse_misp(payload, "misp-intel")
        self.assertEqual(Ioc.batch_create(items), 1)
        # 重复灌同一条
        self.assertEqual(Ioc.batch_create(items), 0)
        self.assertEqual(len(Ioc.list()), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
