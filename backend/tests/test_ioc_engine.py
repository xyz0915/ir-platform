#!/usr/bin/env python3
"""规则引擎动态引用 iocs 表的回归测试套件.

测试目标（对应需求 1、2）:
  a. 往 iocs 表插入一个 enabled 的 ip 类型指标，构造/取一条匹配 remote_address 的
     list 规则，evaluate 一条 remote_address=该 ip 的数据 → 断言命中。
  b. 现有静态 values 仍命中（使用 default_rules.json 中 known_bad_ip_1 规则的 field/value）。
  c. 插入一个 disabled 的 ioc → 断言不命中。
  d. iocs 表为空时，现有规则匹配行为不变（与 b 合并覆盖）。

设计要点:
  - 使用独立临时 DB，setuptools init_db() 载入默认规则与默认 IOC 种子。
  - evaluate 入口会在 global_context["iocs_by_type"] 注入 enabled=1 的 IOC，
    因此无需手动构造 global_context。
  - 不修改任何业务检测逻辑，只验证"动态引用"的正确性。
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

# 确保后端目录在 Python 路径中（与仓库内其它测试一致）
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings  # noqa: E402

# 独立测试库，避免污染开发/基线库
TEST_DB_PATH = str(BACKEND_DIR / "data" / "test_ioc_engine.db")

# 默认 ioc 类规则文件（用于直接读取已知规则的 field/value）
DEFAULT_RULES_PATH = BACKEND_DIR / "app" / "rules" / "default_rules.json"


def _load_default_rules() -> list:
    with open(DEFAULT_RULES_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _find_rule(rules: list, name: str) -> dict:
    for r in rules:
        if r.get("name") == name:
            return r
    raise AssertionError(f"默认规则中未找到 {name}")


class TestIocEngineDynamicReference(unittest.TestCase):
    """验证规则引擎动态引用 iocs 表（enabled=1）."""

    @classmethod
    def setUpClass(cls):
        """初始化独立测试库并载入默认规则/IOC 种子."""
        db_path = Path(TEST_DB_PATH)
        if db_path.exists():
            db_path.unlink()

        settings.DB_PATH = TEST_DB_PATH

        from app.database import init_db

        init_db()

        # 读取默认规则，供 b/d 用例复用
        cls.default_rules = _load_default_rules()
        # 取得一条匹配 remote_address 的 ioc 类 list 规则
        cls.known_bad_ip_rule = _find_rule(cls.default_rules, "known_bad_ip_1")

    @classmethod
    def tearDownClass(cls):
        """清理测试库文件."""
        db_path = Path(TEST_DB_PATH)
        # 不删除文件以保留现场；如需清理可取消注释：
        # if db_path.exists():
        #     db_path.unlink()
        _ = db_path

    def setUp(self):
        """每个用例前清空 iocs 表，保证互相隔离（仅保留 default 种子由用例自行增删）."""
        from app.models.ioc import Ioc

        # 删除全部（含种子），本套用例自行控制数据
        for it in Ioc.list():
            Ioc.delete(it["id"])

    def _make_conn_item(self, remote_address: str) -> dict:
        """构造一条网络连接数据项（供 list 规则匹配 remote_address 字段）."""
        return {
            "remote_address": remote_address,
            "remote_port": 443,
            "protocol": "tcp",
            "process_name": "evil.exe",
        }

    # ── a. 动态 IOC（enabled）命中 ──────────────────────────────────
    def test_enabled_ioc_hits_via_dynamic_reference(self):
        """插入一个 enabled 的 ip 类型 IOC，evaluate 应动态命中远程地址匹配的数据."""
        from app.models.ioc import Ioc
        from app.rules.rule_engine import RuleEngine

        mal_ip = "203.0.113.66"
        Ioc.create(
            ioc_type="ip",
            ioc_value=mal_ip,
            source="user",
            description="动态引用测试 IOC",
            enabled=True,
        )

        # 使用默认 known_bad_ip_1 规则（field=remote_address, list 类型）
        rule = self.known_bad_ip_rule
        self.assertEqual(rule["condition"]["field"], "remote_address")

        data_items = [self._make_conn_item(mal_ip)]
        matches = RuleEngine.evaluate(data_items, [rule])

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["rule_name"], rule["name"])
        # 命中的值应等于动态 IOC 的值
        self.assertEqual(matches[0]["item"]["remote_address"], mal_ip)

    # ── b + d. 现有静态 values 仍命中；iocs 为空时行为不变 ────────
    def test_static_values_still_hits_when_iocs_empty(self):
        """iocs 表为空时，规则 condition.values 的静态黑名单仍应命中（向后兼容）."""
        from app.rules.rule_engine import RuleEngine

        # setUp 已清空 iocs 表 → 此时只依赖规则自带 values
        rule = self.known_bad_ip_rule
        static_ip = rule["condition"]["values"][0]  # 例如 "185.220.101.1"
        self.assertIsNotNone(static_ip)

        data_items = [self._make_conn_item(static_ip)]
        matches = RuleEngine.evaluate(data_items, [rule])

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["item"]["remote_address"], static_ip)

    # ── c. disabled 的 ioc 不命中 ──────────────────────────────────
    def test_disabled_ioc_does_not_hit(self):
        """插入一个 disabled 的 ip 类型 IOC，evaluate 不应命中（动态引用只看 enabled=1）."""
        from app.models.ioc import Ioc
        from app.rules.rule_engine import RuleEngine

        mal_ip = "203.0.113.99"
        Ioc.create(
            ioc_type="ip",
            ioc_value=mal_ip,
            source="user",
            description="禁用态 IOC，不应命中",
            enabled=False,
        )

        rule = self.known_bad_ip_rule
        data_items = [self._make_conn_item(mal_ip)]
        matches = RuleEngine.evaluate(data_items, [rule])

        self.assertEqual(len(matches), 0)

    # ── 补充：不同 field 映射（domain 类规则）─────────────────────
    def test_domain_type_ioc_hits_via_host_field(self):
        """验证 domain 类型 IOC 通过 host 字段映射动态命中（映射正确性）."""
        from app.models.ioc import Ioc
        from app.rules.rule_engine import RuleEngine

        evil_domain = "evil-dynamic.example.com"
        Ioc.create(
            ioc_type="domain",
            ioc_value=evil_domain,
            source="user",
            enabled=True,
        )

        # 构造一条匹配 host 字段的 list 规则（field=host → domain）
        rule = {
            "name": "dynamic_domain_rule",
            "rule_type": "list",
            "condition": {"field": "host", "values": [], "match_mode": "exact"},
        }
        data_items = [{"host": evil_domain, "remote_address": "1.2.3.4"}]
        matches = RuleEngine.evaluate(data_items, [rule])

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["item"]["host"], evil_domain)

    # ── 补充：PUT 端点让启用开关真正生效（需求 2 闭环）────────────
    def test_ioc_update_toggles_enabled(self):
        """Ioc.update() 应能把 enabled 置为 False，从而影响动态引用命中结果."""
        from app.models.ioc import Ioc
        from app.rules.rule_engine import RuleEngine

        mal_ip = "203.0.113.77"
        created = Ioc.create(
            ioc_type="ip",
            ioc_value=mal_ip,
            source="user",
            enabled=True,
        )
        ioc_id = created["id"]

        # 先确认启用时命中
        rule = self.known_bad_ip_rule
        self.assertEqual(len(RuleEngine.evaluate([self._make_conn_item(mal_ip)], [rule])), 1)

        # 通过 update 关闭启用
        updated = Ioc.update(ioc_id, enabled=False)
        self.assertFalse(updated["enabled"])

        # 关闭后不应命中
        self.assertEqual(len(RuleEngine.evaluate([self._make_conn_item(mal_ip)], [rule])), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
