#!/usr/bin/env python3
"""独立全量回归验证脚本 —— 外部威胁源拉取与灌表 (ioc_feed_sync.py).

说明:
  - 本脚本 **独立** 于 shipped 的 test_ioc_feed.py，用作 QA 二次验证（不橡皮图章）。
  - 全程使用 **临时隔离数据库**（tempfile），并在每个用例前清空 iocs 表，互不污染。
  - **不发起任何真实网络请求**：解析器为纯函数；端到端 sync_feed 通过 monkeypatch
    替换 fetch_feed_text 来模拟拉取返回。
  - 逐项实跑断言，输出清晰 PASS/FAIL 汇总，并以进程退出码反映结论（0=全过）。

运行:
  backend/venv/Scripts/python.exe backend/qa_ioc_feed_verify.py
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# 必须在导入任何 app 模块前，把测试库路径固定到临时文件
_BACKEND_DIR = Path(__file__).resolve().parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))
_SCRIPTS_DIR = _BACKEND_DIR / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from app.config import settings  # noqa: E402

# 固定到临时 DB（覆盖默认 ir_platform.db，避免污染开发/基线库）
_TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False, dir=str(_BACKEND_DIR / "data"))
_TMP_DB.close()
settings.DB_PATH = _TMP_DB.name

import ioc_feed_sync  # noqa: E402  (在设置 DB_PATH 后导入，确保连的是临时库)
from app.models.ioc import Ioc  # noqa: E402


class IocFeedIndependentVerify(unittest.TestCase):
    """独立验证：解析器 / 灌表去重 / 端到端 / 无回归."""

    @classmethod
    def setUpClass(cls):
        from app.database import init_db

        init_db()  # 建表 + 种子（本套用例会自行清空/重建 iocs 数据）

    def setUp(self):
        """每个用例前清空 iocs 表，保证互相隔离."""
        for it in Ioc.list():
            Ioc.delete(it["id"])

    # ───────────────────────── CSV 解析 ─────────────────────────
    def test_csv_type_value_with_type_map(self):
        """type/value 列 + type_map（sha256->hash）映射正确."""
        csv_text = "type,value\nip,1.2.3.4\ndomain,evil.com\nsha256,abcde123\n"
        items = ioc_feed_sync.parse_csv(
            csv_text,
            {"ip": "ip", "domain": "domain", "url": "url", "sha256": "hash"},
            "abuse-ch-csv",
        )
        self.assertEqual(len(items), 3, f"期望 3 条，实际 {len(items)}: {items}")
        by_type = {it["ioc_type"]: it["ioc_value"] for it in items}
        self.assertEqual(by_type["ip"], "1.2.3.4")
        self.assertEqual(by_type["domain"], "evil.com")
        self.assertEqual(by_type["hash"], "abcde123")
        self.assertTrue(all(it["source"] == "abuse-ch-csv" for it in items))

    def test_csv_ioc_type_ioc_value_columns(self):
        """ioc_type/ioc_value 列（已为系统类型）直接采用，并带 description."""
        csv_text = "ioc_type,ioc_value,description\nurl,http://x/y,C2 url\n"
        items = ioc_feed_sync.parse_csv(csv_text, None, "feed-x")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["ioc_type"], "url")
        self.assertEqual(items[0]["ioc_value"], "http://x/y")
        self.assertEqual(items[0]["description"], "C2 url")
        self.assertEqual(items[0]["source"], "feed-x")

    def test_csv_skips_empty_and_missing_value(self):
        """空行 / 缺值行应被跳过，不报错."""
        csv_text = "type,value\nip,1.1.1.1\n,\nip,\ndomain,evil2.com\n"
        items = ioc_feed_sync.parse_csv(csv_text, None, "feed")
        self.assertEqual(len(items), 2, f"期望 2 条，实际 {len(items)}: {items}")
        values = {it["ioc_value"] for it in items}
        self.assertIn("1.1.1.1", values)
        self.assertIn("evil2.com", values)
        self.assertNotIn("", values)

    def test_csv_skips_unknown_type(self):
        """无法映射为合法 ioc_type 的行应被跳过."""
        csv_text = "type,value\nweirdtype,foo\nip,2.2.2.2\n"
        items = ioc_feed_sync.parse_csv(csv_text, None, "feed")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["ioc_value"], "2.2.2.2")
        self.assertEqual(items[0]["ioc_type"], "ip")

    def test_csv_empty_input(self):
        """空文本 / 仅表头不抛异常，返回空列表."""
        self.assertEqual(ioc_feed_sync.parse_csv("", None, "feed"), [])
        self.assertEqual(ioc_feed_sync.parse_csv("type,value\n", None, "feed"), [])

    # ───────────────────────── MISP 解析 ────────────────────────
    def test_misp_event_attribute_mapping(self):
        """Event/Attribute 各类型映射 + 空值/未知类型跳过 + comment 作 description."""
        payload = {
            "Event": [
                {
                    "Attribute": [
                        {"type": "ip-dst", "value": "1.2.3.4", "comment": "note"},
                        {"type": "domain", "value": "evil.com"},
                        {"type": "sha256", "value": "abc"},
                        {"type": "unknown", "value": "x"},
                        {"type": "domain", "value": ""},
                    ]
                }
            ]
        }
        items = ioc_feed_sync.parse_misp(payload, "misp-intel")
        by_value = {it["ioc_value"]: it["ioc_type"] for it in items}
        self.assertEqual(by_value["1.2.3.4"], "ip")
        self.assertEqual(by_value["evil.com"], "domain")
        self.assertEqual(by_value["abc"], "hash")
        # 未知类型与空值被跳过
        self.assertNotIn("x", by_value)
        self.assertNotIn("", by_value)
        self.assertEqual(len(items), 3, f"期望 3 条，实际 {len(items)}: {items}")
        # comment 作为 description
        ip_item = next(it for it in items if it["ioc_value"] == "1.2.3.4")
        self.assertEqual(ip_item["description"], "note")
        self.assertEqual(ip_item["source"], "misp-intel")

    # ───────────────────────── STIX 解析 ────────────────────────
    def test_stix_indicator_pattern_extraction(self):
        """indicator pattern 提取值并映射各类型；非 indicator 对象跳过."""
        bundle = {
            "objects": [
                {"type": "indicator", "pattern": "[ip-addr:value = '9.9.9.9']"},
                {"type": "indicator", "pattern": "[domain-name:value = 'bad.com']"},
                {"type": "indicator", "pattern": "[file:hashes.'SHA-256' = 'deadbeef']"},
                {"type": "malware", "name": "x"},  # 跳过
            ]
        }
        items = ioc_feed_sync.parse_stix(bundle, "stix-bundle")
        by_value = {it["ioc_value"]: it["ioc_type"] for it in items}
        self.assertEqual(by_value["9.9.9.9"], "ip")
        self.assertEqual(by_value["bad.com"], "domain")
        self.assertEqual(by_value["deadbeef"], "hash")
        self.assertEqual(len(items), 3, f"期望 3 条，实际 {len(items)}: {items}")
        self.assertEqual(items[0]["source"], "stix-bundle")

    # ───────────────────── 灌表去重 (batch_create) ──────────────
    def test_batch_create_dedup_within_single_call(self):
        """重复 (ioc_type, ioc_value) 只保留一条."""
        items = [
            {"ioc_type": "ip", "ioc_value": "1.1.1.1", "source": "feed"},
            {"ioc_type": "ip", "ioc_value": "1.1.1.1", "source": "feed"},  # 重复
            {"ioc_type": "domain", "ioc_value": "a.com", "source": "feed"},
            {"ioc_type": "hash", "ioc_value": "dead", "source": "feed"},
        ]
        inserted = Ioc.batch_create(items)
        self.assertEqual(inserted, 3, f"期望插入 3 条，实际 {inserted}")
        self.assertEqual(len(Ioc.list()), 3)
        ips = [i for i in Ioc.list() if i["ioc_type"] == "ip"]
        self.assertEqual(len(ips), 1)

    def test_batch_create_dedup_across_two_calls(self):
        """跨两次 batch_create 仍去重."""
        items_a = [{"ioc_type": "ip", "ioc_value": "7.7.7.7", "source": "feed"}]
        items_b = [{"ioc_type": "ip", "ioc_value": "7.7.7.7", "source": "feed"}]
        self.assertEqual(Ioc.batch_create(items_a), 1)
        self.assertEqual(Ioc.batch_create(items_b), 0, "第二次重复应插入 0 条")
        self.assertEqual(len(Ioc.list()), 1)

    def test_batch_create_skips_empty_fields(self):
        """空 ioc_type / 空 ioc_value 的项被跳过."""
        items = [
            {"ioc_type": "", "ioc_value": "x"},
            {"ioc_type": "ip", "ioc_value": ""},
            {"ioc_type": "url", "ioc_value": "http://ok"},
        ]
        inserted = Ioc.batch_create(items)
        self.assertEqual(inserted, 1)
        self.assertEqual(len(Ioc.list()), 1)

    # ───────────────────── 端到端 (不联网) ──────────────────────
    def test_e2e_csv_sync_feed_source_and_enabled(self):
        """用 parse_csv 结果直接走 sync_feed（mock fetch），断言条数与 source/enabled."""
        csv_text = "type,value\nip,5.5.5.5\nurl,http://5.5.5.5/x\n"
        feed_cfg = {
            "name": "abuse-ch-csv",
            "format": "csv",
            "url": "https://feeds.example.com/iocs.csv",
            "enabled": True,
            "type_map": {"ip": "ip", "url": "url"},
        }
        with mock.patch.object(
            ioc_feed_sync, "fetch_feed_text", return_value=csv_text
        ) as m:
            inserted, parsed = ioc_feed_sync.sync_feed(feed_cfg)
            m.assert_called_once()
        self.assertEqual(parsed, 2)
        self.assertEqual(inserted, 2)
        stored = Ioc.list()
        self.assertEqual(len(stored), 2)
        for it in stored:
            self.assertEqual(it["source"], "abuse-ch-csv")
            self.assertTrue(it["enabled"], "新灌入的 IOC 应默认 enabled=1")

    # ───────────────────── 无回归: iocs 引擎动态引用 ────────────
    def test_no_regression_engine_dynamic_reference(self):
        """确认 ioc_feed_sync 引入后，规则引擎动态引用 iocs 表（enabled=1）仍生效."""
        from app.rules.rule_engine import RuleEngine

        # 读取默认规则，取一条匹配 remote_address 的 ip 类 list 规则
        rules_path = _BACKEND_DIR / "app" / "rules" / "default_rules.json"
        with open(rules_path, "r", encoding="utf-8") as fh:
            default_rules = json.load(fh)
        rule = next(r for r in default_rules if r.get("name") == "known_bad_ip_1")
        self.assertEqual(rule["condition"]["field"], "remote_address")

        # 动态插入一个 enabled 的 ip IOC（区别于规则自带静态 values）
        dynamic_ip = "203.0.113.50"
        Ioc.create(ioc_type="ip", ioc_value=dynamic_ip, source="user", enabled=True)

        matches = RuleEngine.evaluate(
            [{"remote_address": dynamic_ip, "remote_port": 443}], [rule]
        )
        self.assertEqual(len(matches), 1, "enabled 动态 IOC 应被引擎命中")
        self.assertEqual(matches[0]["rule_name"], "known_bad_ip_1")

    def test_no_regression_static_values_still_hit(self):
        """iocs 表为空时，规则自带静态 values 仍命中（向后兼容，引擎逻辑未被破坏）."""
        from app.rules.rule_engine import RuleEngine

        rules_path = _BACKEND_DIR / "app" / "rules" / "default_rules.json"
        with open(rules_path, "r", encoding="utf-8") as fh:
            default_rules = json.load(fh)
        rule = next(r for r in default_rules if r.get("name") == "known_bad_ip_1")
        static_ip = rule["condition"]["values"][0]
        self.assertIsNotNone(static_ip)

        # setUp 已清空 iocs 表
        matches = RuleEngine.evaluate(
            [{"remote_address": static_ip, "remote_port": 443}], [rule]
        )
        self.assertEqual(len(matches), 1, "静态 values 应命中")
        self.assertEqual(matches[0]["item"]["remote_address"], static_ip)


if __name__ == "__main__":
    # 自定义 runner，输出逐项 PASS/FAIL 汇总
    suite = unittest.TestLoader().loadTestsFromTestCase(IocFeedIndependentVerify)
    result = unittest.TextTestRunner(verbosity=2).run(suite)

    total = result.testsRun
    failed = len(result.failures) + len(result.errors)
    passed = total - failed
    print("\n" + "=" * 60)
    print(f"独立验证汇总: 总数={total} 通过={passed} 失败={failed}")
    print(f"临时数据库: {settings.DB_PATH}")
    print("=" * 60)

    # 清理临时 DB 文件
    try:
        Path(settings.DB_PATH).unlink(missing_ok=True)
    except OSError:
        pass

    sys.exit(0 if result.wasSuccessful() else 1)
