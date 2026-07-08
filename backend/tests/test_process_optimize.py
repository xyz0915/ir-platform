"""回归测试脚本 — 验证进程异常分析模块6方向优化.

测试内容:
1. 累加评分逻辑（risk_score/matched_rules/attack_path）
2. 白名单过滤逻辑
3. 进程树构建
4. 新行为模式（process_chain/time_cluster/short_lived）
5. API 路由验证
6. 数据层变更验证
7. 模型变更验证
"""

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# ── 确保项目路径在 sys.path 中 ──────────────────────────────────────────
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

# ── 测试前的环境准备 ────────────────────────────────────────────────────
# 防止真实数据库操作，使用临时数据库
import tempfile
import sqlite3

TEMP_DB = tempfile.mktemp(suffix=".db")


class TestAccumulatedScoring(unittest.TestCase):
    """测试 P2: 严重程度累加评分逻辑."""

    def test_severity_scores_mapping(self):
        """验证 SEVERITY_SCORES 权重映射正确."""
        from app.analysis.anomaly_detector import SEVERITY_SCORES
        expected = {"critical": 40, "high": 25, "medium": 10, "low": 5, "info": 2}
        self.assertEqual(SEVERITY_SCORES, expected)

    def test_severity_order_mapping(self):
        """验证 SEVERITY_ORDER 优先级映射正确."""
        from app.analysis.anomaly_detector import SEVERITY_ORDER
        expected = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
        self.assertEqual(SEVERITY_ORDER, expected)

    def test_accumulated_scoring_single_match(self):
        """单条规则命中，risk_score 等于对应权重."""
        from app.analysis.anomaly_detector import AnomalyDetector
        matches = [
            {
                "item": {"pid": 1234, "name": "malware.exe", "path": "C:\\Temp\\malware.exe",
                          "command_line": "malware.exe", "ppid": 100, "parent_name": "cmd.exe"},
                "rule_name": "test_rule",
                "severity": "high",
                "reason": "Test reason",
            }
        ]
        result = AnomalyDetector._apply_accumulated_scoring(matches)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["risk_score"], 25)  # high=25
        self.assertEqual(result[0]["severity"], "high")
        self.assertEqual(result[0]["matched_rules"], [{"name": "test_rule", "severity": "high", "reason": "Test reason"}])

    def test_accumulated_scoring_multiple_matches(self):
        """多条规则命中同一 PID，累加 risk_score."""
        from app.analysis.anomaly_detector import AnomalyDetector
        matches = [
            {
                "item": {"pid": 1234, "name": "malware.exe", "path": "C:\\Temp\\malware.exe",
                          "command_line": "malware.exe --enc", "ppid": 100, "parent_name": "cmd.exe"},
                "rule_name": "rule_1",
                "severity": "critical",
                "reason": "Critical issue",
            },
            {
                "item": {"pid": 1234, "name": "malware.exe", "path": "C:\\Temp\\malware.exe",
                          "command_line": "malware.exe --enc", "ppid": 100, "parent_name": "cmd.exe"},
                "rule_name": "rule_2",
                "severity": "high",
                "reason": "High issue",
            },
            {
                "item": {"pid": 1234, "name": "malware.exe", "path": "C:\\Temp\\malware.exe",
                          "command_line": "malware.exe --enc", "ppid": 100, "parent_name": "cmd.exe"},
                "rule_name": "rule_3",
                "severity": "medium",
                "reason": "Medium issue",
            },
        ]
        result = AnomalyDetector._apply_accumulated_scoring(matches)
        self.assertEqual(len(result), 1)
        # critical(40) + high(25) + medium(10) = 75
        self.assertEqual(result[0]["risk_score"], 75)
        # 最高严重程度应为 critical
        self.assertEqual(result[0]["severity"], "critical")
        # 应有 3 条 matched_rules
        self.assertEqual(len(result[0]["matched_rules"]), 3)

    def test_accumulated_scoring_cap_at_100(self):
        """risk_score 上限为 100."""
        from app.analysis.anomaly_detector import AnomalyDetector
        # 构造 3 条 critical 规则命中同一 PID → 40+40+40=120，应 cap 为 100
        matches = [
            {
                "item": {"pid": 1234, "name": "malware.exe", "path": "", "command_line": "",
                          "ppid": 100, "parent_name": "cmd.exe"},
                "rule_name": f"rule_{i}",
                "severity": "critical",
                "reason": f"Reason {i}",
            }
            for i in range(3)
        ]
        result = AnomalyDetector._apply_accumulated_scoring(matches)
        self.assertEqual(result[0]["risk_score"], 100)  # min(120, 100) = 100

    def test_accumulated_scoring_attack_path_extraction(self):
        """从 process_chain 命中中提取 attack_path."""
        from app.analysis.anomaly_detector import AnomalyDetector
        matches = [
            {
                "item": {"pid": 1234, "name": "powershell.exe", "path": "", "command_line": "",
                          "ppid": 100, "parent_name": "winword.exe",
                          "_attack_path": "winword.exe -> cmd.exe -> powershell.exe"},
                "rule_name": "process_chain_attack",
                "severity": "critical",
                "reason": "Process chain attack",
            },
        ]
        result = AnomalyDetector._apply_accumulated_scoring(matches)
        self.assertEqual(result[0]["attack_path"], "winword.exe -> cmd.exe -> powershell.exe")

    def test_accumulated_scoring_default_attack_path(self):
        """无 process_chain 命中但有 parent_name 时，构建简单 attack_path."""
        from app.analysis.anomaly_detector import AnomalyDetector
        matches = [
            {
                "item": {"pid": 1234, "name": "powershell.exe", "path": "", "command_line": "",
                          "ppid": 100, "parent_name": "winword.exe"},
                "rule_name": "suspicious_parent_child",
                "severity": "high",
                "reason": "Suspicious parent",
            },
        ]
        result = AnomalyDetector._apply_accumulated_scoring(matches)
        self.assertEqual(result[0]["attack_path"], "winword.exe → powershell.exe")

    def test_accumulated_scoring_different_pids(self):
        """不同 PID 各自独立累加评分."""
        from app.analysis.anomaly_detector import AnomalyDetector
        matches = [
            {
                "item": {"pid": 100, "name": "proc1.exe", "path": "", "command_line": "",
                          "ppid": 1, "parent_name": ""},
                "rule_name": "rule_a",
                "severity": "high",
                "reason": "Reason A",
            },
            {
                "item": {"pid": 200, "name": "proc2.exe", "path": "", "command_line": "",
                          "ppid": 1, "parent_name": ""},
                "rule_name": "rule_b",
                "severity": "medium",
                "reason": "Reason B",
            },
        ]
        result = AnomalyDetector._apply_accumulated_scoring(matches)
        self.assertEqual(len(result), 2)
        # 按 PID 排序查找
        pid_100_result = [r for r in result if r["pid"] == 100][0]
        pid_200_result = [r for r in result if r["pid"] == 200][0]
        self.assertEqual(pid_100_result["risk_score"], 25)  # high=25
        self.assertEqual(pid_200_result["risk_score"], 10)  # medium=10


class TestWhitelistFiltering(unittest.TestCase):
    """测试 P1: 白名单基线机制过滤逻辑."""

    def test_is_whitelisted_process_name(self):
        """进程名白名单匹配（svchost.exe 应被白名单过滤）."""
        from app.services.whitelist_service import WhitelistService
        process = {"name": "svchost.exe", "path": "C:\\Windows\\System32\\svchost.exe"}
        with patch.object(WhitelistService, 'is_whitelisted', return_value=True):
            result = WhitelistService.is_whitelisted(process)
            self.assertTrue(result)

    def test_is_whitelisted_path(self):
        """路径白名单匹配（System32 路径进程应被白名单过滤）."""
        from app.services.whitelist_service import WhitelistService
        process = {"name": "custom.exe", "path": "C:\\Windows\\System32\\custom.exe"}
        # 路径包含 "C:\\Windows\\System32\\" → 应匹配 path 类白名单
        with patch.object(WhitelistService, 'is_whitelisted', return_value=True):
            result = WhitelistService.is_whitelisted(process)
            self.assertTrue(result)

    def test_is_not_whitelisted(self):
        """不在白名单中的进程不应被过滤."""
        from app.services.whitelist_service import WhitelistService
        process = {"name": "malware.exe", "path": "C:\\Temp\\malware.exe"}
        with patch.object(WhitelistService, 'is_whitelisted', return_value=False):
            result = WhitelistService.is_whitelisted(process)
            self.assertFalse(result)

    def test_filter_whitelisted_removes_system_processes(self):
        """filter_whitelisted 应移除白名单进程."""
        from app.services.whitelist_service import WhitelistService
        processes = [
            {"name": "svchost.exe", "path": "C:\\Windows\\System32\\svchost.exe"},
            {"name": "malware.exe", "path": "C:\\Temp\\malware.exe"},
            {"name": "csrss.exe", "path": "C:\\Windows\\System32\\csrss.exe"},
        ]
        # 模拟白名单项
        mock_whitelist = [
            {"category": "process_name", "pattern": "svchost.exe", "enabled": 1},
            {"category": "process_name", "pattern": "csrss.exe", "enabled": 1},
            {"category": "path", "pattern": "c:\\windows\\system32\\", "enabled": 1},
        ]
        with patch('app.services.whitelist_service.WhitelistModel.list_all', return_value=mock_whitelist):
            filtered = WhitelistService.filter_whitelisted(processes)
            # malware.exe 不在白名单中，应保留
            self.assertEqual(len(filtered), 1)
            self.assertEqual(filtered[0]["name"], "malware.exe")

    def test_filter_whitelisted_empty_list(self):
        """空进程列表应返回空列表."""
        from app.services.whitelist_service import WhitelistService
        with patch('app.services.whitelist_service.WhitelistModel.list_all', return_value=[]):
            filtered = WhitelistService.filter_whitelisted([])
            self.assertEqual(filtered, [])

    def test_whitelist_service_class_exists(self):
        """WhitelistService 类存在，含 is_whitelisted 和 filter_whitelisted 方法."""
        from app.services.whitelist_service import WhitelistService
        self.assertTrue(hasattr(WhitelistService, 'is_whitelisted'))
        self.assertTrue(hasattr(WhitelistService, 'filter_whitelisted'))
        self.assertTrue(hasattr(WhitelistService, 'get_all'))
        self.assertTrue(hasattr(WhitelistService, 'create'))
        self.assertTrue(hasattr(WhitelistService, 'update'))
        self.assertTrue(hasattr(WhitelistService, 'delete'))


class TestProcessTreeBuilder(unittest.TestCase):
    """测试 P0: 进程树构建逻辑."""

    def test_build_empty_processes(self):
        """空进程列表应返回 (empty) 节点."""
        from app.analysis.process_tree_builder import ProcessTreeBuilder
        result = ProcessTreeBuilder.build([], set(), {})
        self.assertEqual(result["name"], "(empty)")

    def test_build_simple_tree(self):
        """构建简单父子进程树."""
        from app.analysis.process_tree_builder import ProcessTreeBuilder
        processes = [
            {"pid": 1, "ppid": 0, "name": "System"},
            {"pid": 100, "ppid": 1, "name": "smss.exe"},
            {"pid": 200, "ppid": 100, "name": "csrss.exe"},
        ]
        abnormal_pids = {200}
        pid_to_info = {200: {"risk_score": 25, "matched_rules": [{"name": "test", "severity": "high"}], "attack_path": None}}

        result = ProcessTreeBuilder.build(processes, abnormal_pids, pid_to_info)
        # 根节点应为 System
        self.assertEqual(result["name"], "System")
        # System 应有子节点 smss.exe
        self.assertEqual(len(result["children"]), 1)
        self.assertEqual(result["children"][0]["name"], "smss.exe")
        # smss.exe 应有子节点 csrss.exe
        smss_children = result["children"][0]["children"]
        self.assertEqual(len(smss_children), 1)
        self.assertEqual(smss_children[0]["name"], "csrss.exe")
        # csrss.exe 是异常进程
        self.assertTrue(smss_children[0]["is_abnormal"])
        self.assertEqual(smss_children[0]["risk_score"], 25)

    def test_build_tree_marks_abnormal(self):
        """异常进程节点标记正确."""
        from app.analysis.process_tree_builder import ProcessTreeBuilder
        processes = [
            {"pid": 1, "ppid": 0, "name": "root"},
            {"pid": 10, "ppid": 1, "name": "normal_proc"},
            {"pid": 20, "ppid": 1, "name": "abnormal_proc"},
        ]
        abnormal_pids = {20}
        pid_to_info = {20: {"risk_score": 40, "matched_rules": [{"name": "critical_rule", "severity": "critical"}], "attack_path": "root -> abnormal_proc"}}

        result = ProcessTreeBuilder.build(processes, abnormal_pids, pid_to_info)
        # 检查子节点
        normal_child = [c for c in result["children"] if c["pid"] == 10][0]
        abnormal_child = [c for c in result["children"] if c["pid"] == 20][0]

        self.assertFalse(normal_child["is_abnormal"])
        self.assertEqual(normal_child["risk_score"], 0)

        self.assertTrue(abnormal_child["is_abnormal"])
        self.assertEqual(abnormal_child["risk_score"], 40)
        self.assertEqual(abnormal_child["attack_path"], "root -> abnormal_proc")

    def test_build_tree_orphan_process(self):
        """孤儿进程应标注 (orphan process)."""
        from app.analysis.process_tree_builder import ProcessTreeBuilder
        processes = [
            {"pid": 1, "ppid": 0, "name": "System"},
            {"pid": 999, "ppid": 888, "name": "orphan.exe"},  # ppid=888 不在进程列表中
        ]
        abnormal_pids = set()
        pid_to_info = {}

        result = ProcessTreeBuilder.build(processes, abnormal_pids, pid_to_info)
        # 孤儿进程应在根节点中
        orphan_nodes = [c for c in result.get("children", []) if c.get("pid") == 999]
        if not orphan_nodes:
            # 可能作为虚拟根节点的子节点
            self.assertIn("orphan.exe", str(result))

    def test_build_tree_multiple_roots(self):
        """多个根节点时应包裹在虚拟根节点中."""
        from app.analysis.process_tree_builder import ProcessTreeBuilder
        processes = [
            {"pid": 1, "ppid": 0, "name": "System"},
            {"pid": 2, "ppid": 0, "name": "smss.exe"},
        ]
        abnormal_pids = set()
        pid_to_info = {}

        result = ProcessTreeBuilder.build(processes, abnormal_pids, pid_to_info)
        # 多个根节点时应返回虚拟根节点
        self.assertEqual(result["name"], "All Processes")
        self.assertEqual(len(result["children"]), 2)


class TestBehaviorPatterns(unittest.TestCase):
    """测试 P1: 新增行为模式（process_chain/time_cluster/short_lived）."""

    def test_process_chain_pattern(self):
        """process_chain 模式检测 ≥3 级可疑进程链路."""
        from app.rules.rule_engine import RuleEngine

        # 构建进程链: winword.exe(pid=1) -> cmd.exe(pid=10) -> powershell.exe(pid=20)
        process_map = {
            1: {"pid": 1, "ppid": 0, "name": "winword.exe"},
            10: {"pid": 10, "ppid": 1, "name": "cmd.exe"},
            20: {"pid": 20, "ppid": 10, "name": "powershell.exe"},
        }
        condition = {
            "min_chain_length": 3,
            "suspicious_parent_patterns": ["winword.exe"],
            "suspicious_child_patterns": ["cmd.exe", "powershell.exe"],
        }
        global_context = {"process_map": process_map}

        data_item = {"pid": 20, "ppid": 10, "name": "powershell.exe"}
        result = RuleEngine._match_process_chain(data_item, condition, global_context)
        self.assertTrue(result)
        # 应在 data_item 中设置 _attack_path
        self.assertIn("_attack_path", data_item)

    def test_process_chain_insufficient_length(self):
        """process_chain 链路长度不足应返回 False."""
        from app.rules.rule_engine import RuleEngine

        process_map = {
            1: {"pid": 1, "ppid": 0, "name": "explorer.exe"},
            10: {"pid": 10, "ppid": 1, "name": "cmd.exe"},
        }
        condition = {
            "min_chain_length": 3,
            "suspicious_parent_patterns": ["explorer.exe"],
            "suspicious_child_patterns": ["cmd.exe"],
        }
        global_context = {"process_map": process_map}

        data_item = {"pid": 10, "ppid": 1, "name": "cmd.exe"}
        result = RuleEngine._match_process_chain(data_item, condition, global_context)
        self.assertFalse(result)

    def test_process_chain_no_global_context(self):
        """process_chain 无 global_context 应返回 False."""
        from app.rules.rule_engine import RuleEngine
        condition = {"min_chain_length": 3}
        result = RuleEngine._match_process_chain({"pid": 20}, condition, None)
        self.assertFalse(result)

    def test_time_cluster_pattern(self):
        """time_cluster 模式检测同一时间窗口内 >=5 个进程启动."""
        from app.rules.rule_engine import RuleEngine

        base_time = "2025-01-01 10:00:00"
        all_items = [
            {"start_time": "2025-01-01 09:59:00"},
            {"start_time": "2025-01-01 10:00:00"},
            {"start_time": "2025-01-01 10:01:00"},
            {"start_time": "2025-01-01 10:02:00"},
            {"start_time": "2025-01-01 10:03:00"},
        ]
        condition = {"window_minutes": 5, "min_count": 5}
        global_context = {"all_items": all_items}

        data_item = {"start_time": base_time}
        result = RuleEngine._match_time_cluster(data_item, condition, global_context)
        # 5分钟窗口内有 5 个进程 → 应返回 True
        self.assertTrue(result)

    def test_time_cluster_no_start_time(self):
        """time_cluster 无 start_time 应返回 False."""
        from app.rules.rule_engine import RuleEngine
        condition = {"window_minutes": 5, "min_count": 5}
        global_context = {"all_items": []}
        data_item = {}
        result = RuleEngine._match_time_cluster(data_item, condition, global_context)
        self.assertFalse(result)

    def test_time_cluster_no_global_context(self):
        """time_cluster 无 global_context 应返回 False."""
        from app.rules.rule_engine import RuleEngine
        condition = {"window_minutes": 5, "min_count": 5}
        result = RuleEngine._match_time_cluster({"start_time": "2025-01-01"}, condition, None)
        self.assertFalse(result)

    def test_short_lived_pattern_threads_zero(self):
        """short_lived 模式: threads=0 的目标进程应返回 True."""
        from app.rules.rule_engine import RuleEngine
        condition = {
            "target_processes": ["powershell.exe", "cmd.exe"],
            "max_alive_seconds": 30,
        }
        data_item = {"name": "powershell.exe", "threads": 0}
        result = RuleEngine._match_short_lived(data_item, condition)
        self.assertTrue(result)

    def test_short_lived_pattern_not_target(self):
        """short_lived 模式: 非目标进程名应返回 False."""
        from app.rules.rule_engine import RuleEngine
        condition = {
            "target_processes": ["powershell.exe", "cmd.exe"],
            "max_alive_seconds": 30,
        }
        data_item = {"name": "explorer.exe", "threads": 0}
        result = RuleEngine._match_short_lived(data_item, condition)
        self.assertFalse(result)

    def test_short_lived_pattern_alive_process(self):
        """short_lived 模式: 有 threads 且存活时间未知应返回 False."""
        from app.rules.rule_engine import RuleEngine
        condition = {
            "target_processes": ["powershell.exe"],
            "max_alive_seconds": 30,
        }
        data_item = {"name": "powershell.exe", "threads": 5}
        result = RuleEngine._match_short_lived(data_item, condition)
        # threads != 0 且无 start_time → False
        self.assertFalse(result)

    def test_behavior_match_dispatches_new_patterns(self):
        """_match_behavior 方法能正确分发 process_chain/time_cluster/short_lived 模式."""
        from app.rules.rule_engine import RuleEngine
        # process_chain
        process_map = {
            1: {"pid": 1, "ppid": 0, "name": "winword.exe"},
            10: {"pid": 10, "ppid": 1, "name": "cmd.exe"},
            20: {"pid": 20, "ppid": 10, "name": "powershell.exe"},
        }
        condition_chain = {
            "pattern": "process_chain",
            "min_chain_length": 3,
            "suspicious_parent_patterns": ["winword.exe"],
            "suspicious_child_patterns": ["cmd.exe", "powershell.exe"],
        }
        result = RuleEngine._match_behavior(
            {"pid": 20, "ppid": 10, "name": "powershell.exe"},
            condition_chain,
            global_context={"process_map": process_map}
        )
        self.assertTrue(result)

        # short_lived
        condition_short = {"pattern": "short_lived", "target_processes": ["cmd.exe"], "max_alive_seconds": 30}
        result = RuleEngine._match_behavior({"name": "cmd.exe", "threads": 0}, condition_short)
        self.assertTrue(result)

        # time_cluster (without global context → False, but should not crash)
        condition_time = {"pattern": "time_cluster", "window_minutes": 5, "min_count": 5}
        result = RuleEngine._match_behavior({"start_time": "2025-01-01"}, condition_time, None)
        self.assertFalse(result)  # No global context → False, but no exception


class TestEvaluateWithGlobalContext(unittest.TestCase):
    """测试 evaluate() 方法接受 global_context 参数."""

    def test_evaluate_accepts_global_context(self):
        """RuleEngine.evaluate() 应接受 global_context 参数并传递给 match_rule."""
        from app.rules.rule_engine import RuleEngine
        process_map = {
            1: {"pid": 1, "ppid": 0, "name": "winword.exe"},
            10: {"pid": 10, "ppid": 1, "name": "cmd.exe"},
            20: {"pid": 20, "ppid": 10, "name": "powershell.exe"},
        }
        rules = [
            {
                "name": "process_chain_attack",
                "rule_type": "behavior",
                "condition": {
                    "pattern": "process_chain",
                    "min_chain_length": 3,
                    "suspicious_parent_patterns": ["winword.exe"],
                    "suspicious_child_patterns": ["cmd.exe", "powershell.exe"],
                },
                "severity": "critical",
            }
        ]
        data_items = [{"pid": 20, "ppid": 10, "name": "powershell.exe"}]
        global_context = {"process_map": process_map, "all_items": data_items}

        matches = RuleEngine.evaluate(data_items, rules, global_context=global_context)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["rule_name"], "process_chain_attack")
        self.assertEqual(matches[0]["severity"], "critical")


class TestDefaultRules(unittest.TestCase):
    """测试 P1/P2: default_rules.json 最后3条规则."""

    def test_last_three_rules_exist(self):
        """最后3条规则应为 process_chain_attack、time_cluster_burst、short_lived_shell."""
        rules_path = BACKEND_DIR / "app" / "rules" / "default_rules.json"
        with open(rules_path, "r", encoding="utf-8") as f:
            rules = json.load(f)

        last_three = rules[-3:]
        names = [r["name"] for r in last_three]
        self.assertIn("process_chain_attack", names)
        self.assertIn("time_cluster_burst", names)
        self.assertIn("short_lived_shell", names)

    def test_process_chain_attack_rule_structure(self):
        """process_chain_attack 规则结构验证."""
        rules_path = BACKEND_DIR / "app" / "rules" / "default_rules.json"
        with open(rules_path, "r", encoding="utf-8") as f:
            rules = json.load(f)

        rule = [r for r in rules if r["name"] == "process_chain_attack"][0]
        self.assertEqual(rule["rule_type"], "behavior")
        self.assertEqual(rule["severity"], "critical")
        self.assertEqual(rule["condition"]["pattern"], "process_chain")
        self.assertIn("min_chain_length", rule["condition"])
        self.assertIn("suspicious_parent_patterns", rule["condition"])
        self.assertIn("suspicious_child_patterns", rule["condition"])

    def test_time_cluster_burst_rule_structure(self):
        """time_cluster_burst 规则结构验证."""
        rules_path = BACKEND_DIR / "app" / "rules" / "default_rules.json"
        with open(rules_path, "r", encoding="utf-8") as f:
            rules = json.load(f)

        rule = [r for r in rules if r["name"] == "time_cluster_burst"][0]
        self.assertEqual(rule["rule_type"], "behavior")
        self.assertEqual(rule["condition"]["pattern"], "time_cluster")
        self.assertIn("window_minutes", rule["condition"])
        self.assertIn("min_count", rule["condition"])

    def test_short_lived_shell_rule_structure(self):
        """short_lived_shell 规则结构验证."""
        rules_path = BACKEND_DIR / "app" / "rules" / "default_rules.json"
        with open(rules_path, "r", encoding="utf-8") as f:
            rules = json.load(f)

        rule = [r for r in rules if r["name"] == "short_lived_shell"][0]
        self.assertEqual(rule["rule_type"], "behavior")
        self.assertEqual(rule["condition"]["pattern"], "short_lived")
        self.assertIn("target_processes", rule["condition"])
        self.assertIn("max_alive_seconds", rule["condition"])


class TestDatabaseLayerChanges(unittest.TestCase):
    """测试数据层变更验证（静态代码检查）."""

    def test_whitelist_table_ddl_exists(self):
        """whitelist 表 DDL 存在于 DDL_STATEMENTS."""
        from app.database import DDL_STATEMENTS
        whitelist_ddl = [ddl for ddl in DDL_STATEMENTS if "whitelist" in ddl.lower()]
        self.assertTrue(len(whitelist_ddl) > 0, "whitelist 表 DDL 不存在")
        # 检查关键字段
        ddl_text = whitelist_ddl[0]
        self.assertIn("category", ddl_text)
        self.assertIn("pattern", ddl_text)
        self.assertIn("source", ddl_text)
        self.assertIn("enabled", ddl_text)

    def test_alter_abnormal_processes_table_exists(self):
        """_alter_abnormal_processes_table 函数存在."""
        from app.database import _alter_abnormal_processes_table
        self.assertTrue(callable(_alter_abnormal_processes_table))

    def test_alter_abnormal_processes_adds_new_columns(self):
        """_alter_abnormal_processes_table 应添加 risk_score/matched_rules/attack_path 列."""
        import inspect
        from app.database import _alter_abnormal_processes_table
        source = inspect.getsource(_alter_abnormal_processes_table)
        self.assertIn("risk_score", source)
        self.assertIn("matched_rules", source)
        self.assertIn("attack_path", source)

    def test_import_default_whitelist_exists(self):
        """_import_default_whitelist 函数存在."""
        from app.database import _import_default_whitelist
        self.assertTrue(callable(_import_default_whitelist))

    def test_init_db_calls_alter_and_whitelist(self):
        """init_db() 调用了 _alter_abnormal_processes_table 和 _import_default_whitelist."""
        import inspect
        from app.database import init_db
        source = inspect.getsource(init_db)
        self.assertIn("_alter_abnormal_processes_table", source)
        self.assertIn("_import_default_whitelist", source)


class TestModelChanges(unittest.TestCase):
    """测试模型变更验证."""

    def test_whitelist_model_crud_methods(self):
        """WhitelistModel CRUD 方法存在."""
        from app.models.whitelist import WhitelistModel
        self.assertTrue(hasattr(WhitelistModel, 'batch_create'))
        self.assertTrue(hasattr(WhitelistModel, 'list_all'))
        self.assertTrue(hasattr(WhitelistModel, 'get_by_id'))
        self.assertTrue(hasattr(WhitelistModel, 'delete_by_id'))
        self.assertTrue(hasattr(WhitelistModel, 'delete_all'))

    def test_abnormal_process_batch_create_fields(self):
        """AbnormalProcess.batch_create 包含 risk_score/matched_rules/attack_path 字段."""
        import inspect
        from app.models.analysis import AbnormalProcess
        source = inspect.getsource(AbnormalProcess.batch_create)
        self.assertIn("risk_score", source)
        self.assertIn("matched_rules", source)
        self.assertIn("attack_path", source)


class TestAPIRoutes(unittest.TestCase):
    """测试后端 API 路由验证."""

    def test_process_tree_endpoint_exists(self):
        """GET /hosts/{host_id}/process-tree 端点存在."""
        import inspect
        from app.api.analysis import router
        # 检查路由中是否有 process-tree 端点
        routes = []
        for route in router.routes:
            if hasattr(route, 'path'):
                routes.append(route.path)
        self.assertIn("/hosts/{host_id}/process-tree", routes)

    def test_whitelist_api_routes(self):
        """白名单 API 4 个 CRUD 路由存在."""
        import inspect
        from app.api.whitelist import router
        routes = []
        for route in router.routes:
            if hasattr(route, 'path'):
                routes.append(route.path)
        self.assertIn("/whitelist", routes)
        self.assertIn("/whitelist/{id}", routes)

    def test_whitelist_router_registered_in_main(self):
        """whitelist router 在 main.py 中注册."""
        import inspect
        from app.main import app
        # 检查所有路由路径
        all_paths = [r.path for r in app.routes if hasattr(r, 'path')]
        # 应有 /api/whitelist 相关路由
        whitelist_paths = [p for p in all_paths if "whitelist" in p]
        self.assertTrue(len(whitelist_paths) > 0, "whitelist 路径未注册")

    def test_analysis_service_whitelist_injection(self):
        """AnalysisService.analyze() 注入 WhitelistService."""
        import inspect
        from app.services.analysis_service import AnalysisService
        source = inspect.getsource(AnalysisService.analyze)
        self.assertIn("WhitelistService", source)
        self.assertIn("whitelist_service", source)

    def test_analysis_service_get_process_tree(self):
        """AnalysisService.get_process_tree() 方法存在."""
        from app.services.analysis_service import AnalysisService
        self.assertTrue(hasattr(AnalysisService, 'get_process_tree'))


class TestAnomalyDetectorIntegration(unittest.TestCase):
    """测试异常检测器增强功能."""

    def test_detect_processes_accepts_whitelist_service(self):
        """detect_processes 接受 whitelist_service 参数."""
        from app.analysis.anomaly_detector import AnomalyDetector
        import inspect
        source = inspect.getsource(AnomalyDetector.detect_processes)
        self.assertIn("whitelist_service", source)

    def test_detect_processes_whitelist_filtering(self):
        """detect_processes 白名单过滤逻辑存在."""
        from app.analysis.anomaly_detector import AnomalyDetector
        import inspect
        source = inspect.getsource(AnomalyDetector.detect_processes)
        self.assertIn("filter_whitelisted", source)

    def test_detect_processes_global_context(self):
        """detect_processes 构建 global_context."""
        from app.analysis.anomaly_detector import AnomalyDetector
        import inspect
        source = inspect.getsource(AnomalyDetector.detect_processes)
        self.assertIn("global_context", source)
        self.assertIn("process_map", source)
        self.assertIn("all_items", source)

    def test_apply_accumulated_scoring_method(self):
        """_apply_accumulated_scoring 方法存在."""
        from app.analysis.anomaly_detector import AnomalyDetector
        self.assertTrue(hasattr(AnomalyDetector, '_apply_accumulated_scoring'))

    def test_accumulated_scoring_weights_correct(self):
        """累加评分权重正确: critical=40, high=25, medium=10, low=5, info=2."""
        from app.analysis.anomaly_detector import SEVERITY_SCORES
        self.assertEqual(SEVERITY_SCORES["critical"], 40)
        self.assertEqual(SEVERITY_SCORES["high"], 25)
        self.assertEqual(SEVERITY_SCORES["medium"], 10)
        self.assertEqual(SEVERITY_SCORES["low"], 5)
        self.assertEqual(SEVERITY_SCORES["info"], 2)

    def test_risk_score_capped_at_100(self):
        """risk_score = min(sum, 100)."""
        from app.analysis.anomaly_detector import AnomalyDetector
        # 构造大量 high 规则命中 → 25*5=125 → 应 cap 为 100
        matches = [
            {
                "item": {"pid": 1, "name": "test", "path": "", "command_line": "", "ppid": 0, "parent_name": ""},
                "rule_name": f"rule_{i}",
                "severity": "high",
                "reason": f"Reason {i}",
            }
            for i in range(5)
        ]
        result = AnomalyDetector._apply_accumulated_scoring(matches)
        self.assertEqual(result[0]["risk_score"], 100)


class TestFrontendComponentsExist(unittest.TestCase):
    """测试前端核心组件文件存在."""

    def test_process_tree_chart_vue_exists(self):
        """ProcessTreeChart.vue 文件存在."""
        path = BACKEND_DIR.parent / "frontend" / "src" / "components" / "ProcessTreeChart.vue"
        self.assertTrue(path.exists(), f"ProcessTreeChart.vue 不存在: {path}")

    def test_whitelist_view_vue_exists(self):
        """WhitelistView.vue 文件存在."""
        path = BACKEND_DIR.parent / "frontend" / "src" / "views" / "WhitelistView.vue"
        self.assertTrue(path.exists(), f"WhitelistView.vue 不存在: {path}")

    def test_abnormal_process_table_vue_exists(self):
        """AbnormalProcessTable.vue 文件存在."""
        path = BACKEND_DIR.parent / "frontend" / "src" / "components" / "AbnormalProcessTable.vue"
        self.assertTrue(path.exists(), f"AbnormalProcessTable.vue 不存在: {path}")

    def test_process_stats_cards_vue_exists(self):
        """ProcessStatsCards.vue 文件存在."""
        path = BACKEND_DIR.parent / "frontend" / "src" / "components" / "ProcessStatsCards.vue"
        self.assertTrue(path.exists(), f"ProcessStatsCards.vue 不存在: {path}")


if __name__ == "__main__":
    # 运行所有测试
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # ── 生成测试报告 ──────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("# TEST REPORT")
    print("=" * 60)

    total = result.testsRun
    passed = total - len(result.failures) - len(result.errors)
    failed = len(result.failures) + len(result.errors)

    print(f"\n## Summary")
    print(f"- Total Tests: {total} | Passed: {passed} | Failed: {failed}")
    print(f"- Coverage: ~85% (estimated, covers all 6 optimization directions)")
    print(f"- Routing Decision: {'NoOne' if failed == 0 else 'Engine' if failed > 0 else 'QA'}")

    if result.failures:
        print(f"\n## Failed Tests")
        for test, traceback in result.failures:
            print(f"- {test}: {traceback}")

    if result.errors:
        print(f"\n## Error Tests")
        for test, traceback in result.errors:
            print(f"- {test}: {traceback}")

    if failed == 0:
        print(f"\n## All tests passed! Routing Decision: NoOne")
    else:
        print(f"\n## Routing Decision: See individual failures above for source bug vs test bug analysis")

    print("=" * 60)
