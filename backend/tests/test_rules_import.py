#!/usr/bin/env python3
"""规则导入 Bug 修复验证 — 专项测试套件.

测试范围:
  1. init_db() 后规则数量 = 94（非 32）
  2. 14 个类别全覆盖
  3. 所有规则类型 (regex/list/threshold/behavior/composite)
  4. MITRE ATT&CK 映射验证
  5. 重复执行 init_db() 幂等性
  6. 用户自定义规则保留
  7. 规则更新验证

运行方式:
    cd backend
    venv\\Scripts\\python.exe tests\\test_rules_import.py
"""

import json
import os
import random
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

# 确保后端目录在 Python 路径中
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

# 测试用临时数据库路径
TEST_DB_PATH = str(BACKEND_DIR / "data" / "test_rules_import.db")

# 默认规则文件路径（用于动态推导预期规则数，避免硬编码 94/97 与实际 JSON 不一致，T-P0-1）
DEFAULT_RULES_PATH = BACKEND_DIR / "app" / "rules" / "default_rules.json"
# 攻击链默认规则文件（v1.2.0 新增，load_default_rules() 会一并注入）
DEFAULT_ATTACK_CHAIN_PATH = BACKEND_DIR / "app" / "rules" / "default_attack_chain.json"
# 进程检测加强规则（本次特性新增，随 loader 一并注入）
PROCESS_ENHANCEMENT_PATH = BACKEND_DIR / "app" / "rules" / "process_enhancement_rules.json"
SEED_RULES_PROCESS_PATH = BACKEND_DIR / "app" / "rules" / "seed_rules_process.json"


class TestRulesImportFix(unittest.TestCase):
    """测试 _import_default_rules() upsert-by-name 修复."""

    # ── 预期常量 ──────────────────────────────────────────────
    # 动态推导：所有随 loader 自动注入的规则文件条数之和
    # （default_rules + default_attack_chain + 进程检测加强规则 + seed 进程规则），
    # 避免与硬编码值漂移（T-P0-1）
    EXPECTED_RULE_COUNT = (
        len(json.load(open(DEFAULT_RULES_PATH, "r", encoding="utf-8")))
        + len(json.load(open(DEFAULT_ATTACK_CHAIN_PATH, "r", encoding="utf-8")))
        + len(json.load(open(PROCESS_ENHANCEMENT_PATH, "r", encoding="utf-8")))
        + len(json.load(open(SEED_RULES_PROCESS_PATH, "r", encoding="utf-8")))
    )
    EXPECTED_CATEGORIES = {
        "process", "network", "startup", "persistence", "ioc",
        "behavior", "execution", "credential", "defense_evasion",
        "discovery", "privilege_escalation", "lateral", "exfiltration", "impact",
    }
    # default_rules.json 中实际存在的类型（5 种）
    EXPECTED_RULE_TYPES = {"regex", "list", "threshold", "behavior", "composite"}

    @classmethod
    def setUpClass(cls):
        """测试类初始化：删除旧测试库，设置 DB_PATH，执行 init_db."""
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

    # ── 辅助方法 ──────────────────────────────────────────────

    def _get_rules_from_db(self):
        """从测试数据库读取所有规则."""
        conn = sqlite3.connect(TEST_DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM rules").fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def _get_rule_count(self):
        """获取规则数量."""
        conn = sqlite3.connect(TEST_DB_PATH)
        count = conn.execute("SELECT COUNT(*) FROM rules").fetchone()[0]
        conn.close()
        return count

    # ── 测试 1: 数据库规则数量验证 ─────────────────────────────

    def test_01_rule_count_equals_94(self):
        """执行 init_db() 后，rules 表应有 94 条规则."""
        count = self._get_rule_count()
        self.assertEqual(
            count, self.EXPECTED_RULE_COUNT,
            f"规则数应为 {self.EXPECTED_RULE_COUNT}，实际为 {count}"
        )

    # ── 测试 2: 类别覆盖验证 ──────────────────────────────────

    def test_02_all_14_categories_present(self):
        """确认 14 个类别全部存在."""
        rules = self._get_rules_from_db()
        actual_categories = {r.get("category", "") for r in rules}

        missing = self.EXPECTED_CATEGORIES - actual_categories
        extra = actual_categories - self.EXPECTED_CATEGORIES

        self.assertSetEqual(
            actual_categories & self.EXPECTED_CATEGORIES,
            self.EXPECTED_CATEGORIES,
            f"缺少类别: {missing}\n多余类别: {extra}"
        )

    def test_02b_each_category_has_rules(self):
        """每个类别至少包含 1 条规则."""
        rules = self._get_rules_from_db()
        cat_count = {}
        for r in rules:
            cat = r.get("category", "")
            cat_count[cat] = cat_count.get(cat, 0) + 1

        for cat in self.EXPECTED_CATEGORIES:
            self.assertIn(cat, cat_count, f"类别 '{cat}' 无任何规则")
            self.assertGreater(cat_count[cat], 0, f"类别 '{cat}' 规则数为 0")

    # ── 测试 3: 规则类型验证 ──────────────────────────────────

    def test_03_all_rule_types_present(self):
        """确认包含所有规则类型."""
        rules = self._get_rules_from_db()
        actual_types = {r.get("rule_type", "") for r in rules}

        missing = self.EXPECTED_RULE_TYPES - actual_types
        self.assertTrue(
            self.EXPECTED_RULE_TYPES.issubset(actual_types),
            f"缺少规则类型: {missing}。实际类型: {sorted(actual_types)}"
        )

    def test_03b_each_type_has_rules(self):
        """每种规则类型至少包含 1 条规则."""
        rules = self._get_rules_from_db()
        type_count = {}
        for r in rules:
            rt = r.get("rule_type", "")
            type_count[rt] = type_count.get(rt, 0) + 1

        for rt in self.EXPECTED_RULE_TYPES:
            self.assertIn(rt, type_count, f"规则类型 '{rt}' 无任何规则")
            self.assertGreater(type_count[rt], 0, f"规则类型 '{rt}' 规则数为 0")

    # ── 测试 4: MITRE ATT&CK 映射验证 ─────────────────────────

    def test_04_mitre_attack_mapping(self):
        """随机抽 10 条规则，确认 condition._meta.mitre_attack 存在且非空."""
        rules = self._get_rules_from_db()
        random.seed(42)
        sample = random.sample(rules, min(10, len(rules)))

        missing_meta = []
        empty_attack = []

        for rule in sample:
            condition = rule.get("condition", {})
            # condition 可能是 JSON 字符串或已解析的字典
            if isinstance(condition, str):
                try:
                    condition = json.loads(condition)
                except (json.JSONDecodeError, TypeError):
                    missing_meta.append(rule["name"])
                    continue

            meta = condition.get("_meta", {})
            if not meta:
                missing_meta.append(rule["name"])
                continue

            mitre = meta.get("mitre_attack", "")
            if not mitre:
                empty_attack.append(rule["name"])

        self.assertEqual(
            len(missing_meta), 0,
            f"以下规则缺少 _meta 字段: {missing_meta}"
        )
        self.assertEqual(
            len(empty_attack), 0,
            f"以下规则 mitre_attack 为空: {empty_attack}"
        )

    def test_04b_all_rules_have_mitre_mapping(self):
        """所有规则都应该有 MITRE ATT&CK 映射（更严格的验证）."""
        rules = self._get_rules_from_db()
        missing = []

        for rule in rules:
            condition = rule.get("condition", {})
            if isinstance(condition, str):
                try:
                    condition = json.loads(condition)
                except (json.JSONDecodeError, TypeError):
                    missing.append(f"{rule['name']} (JSON parse error)")
                    continue
            meta = condition.get("_meta", {})
            mitre = meta.get("mitre_attack", "") if meta else ""
            if not mitre:
                missing.append(rule["name"])

        self.assertEqual(
            len(missing), 0,
            f"以下 {len(missing)} 条规则缺少 MITRE ATT&CK 映射: {missing[:20]}..."
        )

    # ── 测试 5: 重复执行幂等性 ────────────────────────────────

    def test_05_idempotent_init_db(self):
        """连续执行 init_db() 两次，规则数仍为 94（不重复插入/不丢失）."""
        from app.config import settings
        from app.database import init_db

        # 第一次 count（setUpClass 已执行过一次）
        count_before = self._get_rule_count()
        self.assertEqual(count_before, self.EXPECTED_RULE_COUNT)

        # 再次执行 init_db
        settings.DB_PATH = TEST_DB_PATH
        init_db()

        count_after = self._get_rule_count()
        self.assertEqual(
            count_after, self.EXPECTED_RULE_COUNT,
            f"幂等性失败: 初始={count_before}, 再次init_db后={count_after}"
        )

    # ── 测试 6: 用户自定义规则保留 ────────────────────────────

    def test_06_user_custom_rule_preserved(self):
        """手动 INSERT 自定义规则后再次 init_db()，确认该规则仍存在."""
        from app.config import settings
        from app.database import init_db

        # 插入自定义规则
        conn = sqlite3.connect(TEST_DB_PATH)
        conn.execute(
            """
            INSERT INTO rules (name, description, category, rule_type, condition, severity, enabled)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "qa_test_custom_rule",
                "QA test custom rule - should survive re-import",
                "custom_test",
                "regex",
                json.dumps({"field": "test_field", "pattern": "qa_marker", "_meta": {"mitre_attack": "TEST001"}}, ensure_ascii=False),
                "low",
                1,
            ),
        )
        conn.commit()
        conn.close()

        # 确认插入成功
        count_after_insert = self._get_rule_count()
        self.assertEqual(count_after_insert, self.EXPECTED_RULE_COUNT + 1)

        # 再次执行 init_db
        settings.DB_PATH = TEST_DB_PATH
        init_db()

        # 确认自定义规则仍在
        conn = sqlite3.connect(TEST_DB_PATH)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM rules WHERE name = 'qa_test_custom_rule'"
        ).fetchone()
        conn.close()

        self.assertIsNotNone(row, "用户自定义规则 'qa_test_custom_rule' 被误删除！")
        self.assertEqual(dict(row)["category"], "custom_test")

        # 总数应为 94 + 1
        count_after_reinit = self._get_rule_count()
        self.assertEqual(
            count_after_reinit, self.EXPECTED_RULE_COUNT + 1,
            f"自定义规则应保留，总数应为 {self.EXPECTED_RULE_COUNT + 1}，实际 {count_after_reinit}"
        )

    # ── 测试 7: 规则更新验证 ──────────────────────────────────

    def test_07_rule_severity_update(self):
        """修改 default_rules.json 中某条规则的 severity，重新 init_db() 后 DB 中的值应更新."""
        from app.config import settings
        from app.database import init_db

        # 找到一条 severity 不是 'critical' 的规则用于测试
        rules = self._get_rules_from_db()
        target_rule = None
        for r in rules:
            if r.get("severity") != "critical" and r.get("name"):
                target_rule = r
                break

        self.assertIsNotNone(target_rule, "找不到可用于测试更新的规则")

        rule_name = target_rule["name"]
        original_severity = target_rule.get("severity", "medium")

        # 读取并修改 default_rules.json
        rules_path = Path(settings.BACKEND_DIR) / "app" / "rules" / "default_rules.json"
        with open(rules_path, "r", encoding="utf-8") as f:
            original_json = f.read()
            rules_data = json.loads(original_json)

        # 找到对应规则并修改 severity 为 'critical'
        found = False
        for rule in rules_data:
            if rule.get("name") == rule_name:
                rule["severity"] = "critical"
                found = True
                break

        self.assertTrue(found, f"在 default_rules.json 中找不到规则 '{rule_name}'")

        # 写回修改后的 JSON
        try:
            with open(rules_path, "w", encoding="utf-8") as f:
                json.dump(rules_data, f, ensure_ascii=False, indent=2)

            # 重新 init_db
            settings.DB_PATH = TEST_DB_PATH
            init_db()

            # 验证 DB 中 severity 已更新
            conn = sqlite3.connect(TEST_DB_PATH)
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT severity FROM rules WHERE name = ?", (rule_name,)
            ).fetchone()
            conn.close()

            self.assertIsNotNone(row, f"规则 '{rule_name}' 在重新导入后丢失")
            self.assertEqual(
                row["severity"], "critical",
                f"规则 '{rule_name}' 的 severity 未更新: 期望 'critical', 实际 '{row['severity']}'"
            )
        finally:
            # 恢复原始 default_rules.json
            with open(rules_path, "w", encoding="utf-8") as f:
                f.write(original_json)

    # ── 测试 8: 规则数据完整性 ────────────────────────────────

    def test_08_all_rules_have_required_fields(self):
        """所有规则都有 name, category, rule_type, condition, severity 字段."""
        rules = self._get_rules_from_db()
        required = ["name", "category", "rule_type", "condition", "severity"]

        for rule in rules:
            for field in required:
                self.assertIsNotNone(
                    rule.get(field),
                    f"规则 ID={rule.get('id')} 缺少字段 '{field}'"
                )
                self.assertNotEqual(
                    rule.get(field), "",
                    f"规则 ID={rule.get('id')} 字段 '{field}' 为空字符串"
                )

    def test_09_condition_is_valid_json_or_dict(self):
        """所有规则的 condition 是可解析的 JSON 或字典."""
        rules = self._get_rules_from_db()
        for rule in rules:
            condition = rule.get("condition")
            self.assertIsNotNone(condition, f"规则 '{rule['name']}' condition 为 None")
            if isinstance(condition, str):
                try:
                    parsed = json.loads(condition)
                    self.assertIsInstance(parsed, dict)
                except json.JSONDecodeError:
                    self.fail(f"规则 '{rule['name']}' condition 不是有效 JSON: {condition[:100]}")
            else:
                self.assertIsInstance(
                    condition, dict,
                    f"规则 '{rule['name']}' condition 应为 dict，实际为 {type(condition)}"
                )

    def test_10_disabled_rules_match_json(self):
        """验证默认规则中 disabled 状态与 JSON 一致（dns_c2_beaconing 和 domain_fronting_detection 默认禁用）."""
        import json as json_mod

        from app.config import settings

        # 读取 JSON 中标记为禁用的规则
        rules_path = Path(settings.BACKEND_DIR) / "app" / "rules" / "default_rules.json"
        with open(rules_path, "r", encoding="utf-8") as f:
            json_rules = json_mod.load(f)

        expected_disabled = {
            r["name"] for r in json_rules
            if r.get("enabled") is False or r.get("enabled") == 0
        }

        # 从 DB 读取实际禁用的规则
        rules = self._get_rules_from_db()
        actual_disabled = set()
        for rule in rules:
            enabled = rule.get("enabled")
            if (isinstance(enabled, bool) and not enabled) or (isinstance(enabled, int) and enabled == 0):
                actual_disabled.add(rule["name"])

        # 验证 JSON 中禁用的规则在 DB 中也禁用
        for name in expected_disabled:
            self.assertIn(
                name, actual_disabled,
                f"JSON 中规则 '{name}' 标记为 disabled=False，但 DB 中已启用"
            )

        # 排除前一步插入的自定义规则，确认 DB 禁用的规则只会是 JSON 中的
        actual_disabled.discard("qa_test_custom_rule")
        unexpected = actual_disabled - expected_disabled
        self.assertEqual(
            len(unexpected), 0,
            f"以下规则在 DB 中被禁用但 JSON 中为启用: {unexpected}"
        )

    # ── 测试 11: severity 枚举约束（T-P1-2）─────────────────────

    def test_11_severity_in_enum(self):
        """所有规则的 severity 必须属于 critical/high/medium/low 枚举."""
        rules = self._get_rules_from_db()
        valid = {"critical", "high", "medium", "low"}
        bad = [r["name"] for r in rules if r.get("severity") not in valid]
        self.assertEqual(
            len(bad), 0,
            f"以下规则 severity 非法（不在枚举内）: {bad}"
        )

    # ── 测试 12: 本地化字段完整性（F-1/F-2）─────────────────────

    def test_12_localization_fields_present(self):
        """所有规则应含 label（中文名），且顶层或 condition._meta 含 mitre_attack."""
        rules = self._get_rules_from_db()
        # 排除 test_06 注入的原始 SQL 自定义规则（无 label/mitre，属测试产物）
        rules = [r for r in rules if r["name"] != "qa_test_custom_rule"]
        no_label = [r["name"] for r in rules if not r.get("label")]
        self.assertEqual(
            len(no_label), 0,
            f"以下规则缺少 label 中文本地化字段: {no_label}"
        )
        no_mitre = []
        for r in rules:
            cond = r.get("condition")
            if isinstance(cond, str):
                try:
                    cond = json.loads(cond)
                except (json.JSONDecodeError, TypeError):
                    cond = {}
            meta = cond.get("_meta", {}) if isinstance(cond, dict) else {}
            mitre = (r.get("mitre_attack")
                     or (meta.get("mitre_attack") if isinstance(meta, dict) else None)
                     or (cond.get("mitre_attack") if isinstance(cond, dict) else None))
            if not mitre:
                no_mitre.append(r["name"])
        self.assertEqual(
            len(no_mitre), 0,
            f"以下规则缺少 mitre_attack 映射: {no_mitre}"
        )


def run_tests():
    """运行所有测试并输出报告."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestRulesImportFix))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result


if __name__ == "__main__":
    print("=" * 70)
    print("  规则导入 Bug 修复验证 — 专项测试套件")
    print("=" * 70)
    print()

    result = run_tests()

    passed = result.testsRun - len(result.failures) - len(result.errors)
    print()
    print("=" * 70)
    print(f"  测试结果: {passed}/{result.testsRun} 通过")
    print(f"  失败: {len(result.failures)}  错误: {len(result.errors)}")
    print("=" * 70)

    sys.exit(0 if result.wasSuccessful() else 1)
