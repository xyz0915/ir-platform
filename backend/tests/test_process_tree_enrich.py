"""进程树 enrich 增强字段 + attack_path 解析 —— 单元测试.

覆盖：
1. enrich=False（缺省）行为向后兼容：节点 dict 不出现任何新字段。
2. enrich=True 增量追加全部新字段，且旧字段保持完整。
3. attack_path 解析：真实格式（进程名 " → " 连接）、"N/M" 约定、list 约定、回退格式、空/失败降级。
4. 派生字段：severity / parent_name / status(运行中/疑似僵尸) / connections。
5. 虚拟根节点 enrich 缺省字段。
6. 兼容性红线：abnormal-processes 端点、AbnormalProcess 模型、采集器均未被触碰（此处仅消费数据）。
"""

import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))


# ─────────────────────────────────────────────────────────────────────────────
# 1. 向后兼容：enrich=False 不新增字段
# ─────────────────────────────────────────────────────────────────────────────

class TestEnrichBackwardCompat(unittest.TestCase):
    def test_default_build_has_no_enrich_fields(self):
        from app.analysis.process_tree_builder import ProcessTreeBuilder
        processes = [
            {"pid": 1, "ppid": 0, "name": "System", "path": "C:\\system", "command_line": "",
             "user": "SYSTEM", "start_time": "2026-07-12T09:30:01", "threads": 5, "connections": []},
            {"pid": 100, "ppid": 1, "name": "cmd.exe", "path": "C:\\cmd", "command_line": "cmd",
             "user": "u", "start_time": "2026-07-12T09:31:00", "threads": 2, "connections": []},
        ]
        abnormal_pids = {100}
        pid_to_info = {100: {"risk_score": 25, "matched_rules": [{"name": "r1"}], "attack_path": None,
                             "severity": "high", "parent_name": "System"}}
        result = ProcessTreeBuilder.build(processes, abnormal_pids, pid_to_info)  # 缺省 enrich=False
        self.assertNotIn("severity", result)
        self.assertNotIn("parent_pid", result)
        self.assertNotIn("parent_name", result)
        self.assertNotIn("start_time", result)
        self.assertNotIn("connections", result)
        self.assertNotIn("attack_chain_step", result)
        # 旧字段仍在
        self.assertIn("name", result)
        self.assertIn("pid", result)
        self.assertIn("children", result)
        child = result["children"][0]
        self.assertNotIn("severity", child)
        self.assertTrue(child["is_abnormal"])

    def test_three_arg_call_still_works(self):
        """旧调用方（仅 3 个位置参数）保持兼容。"""
        from app.analysis.process_tree_builder import ProcessTreeBuilder
        result = ProcessTreeBuilder.build([{"pid": 1, "ppid": 0, "name": "A"}], set(), {})
        self.assertEqual(result["name"], "A")


# ─────────────────────────────────────────────────────────────────────────────
# 2. enrich=True 增量字段
# ─────────────────────────────────────────────────────────────────────────────

class TestEnrichFields(unittest.TestCase):
    def _build(self):
        from app.analysis.process_tree_builder import ProcessTreeBuilder
        processes = [
            {"pid": 1, "ppid": 0, "name": "System", "path": "C:\\system", "command_line": "",
             "user": "SYSTEM", "start_time": "2026-07-12T09:30:01", "threads": 5,
             "connections": [{"protocol": "TCP", "local_address": "10.0.0.1", "local_port": 1111,
                              "remote_address": "45.77.132.9", "remote_port": 4444, "state": "ESTABLISHED"}]},
            {"pid": 100, "ppid": 1, "name": "cmd.exe", "path": "C:\\cmd", "command_line": "cmd",
             "user": "u", "start_time": "2026-07-12T09:31:00", "threads": 0, "connections": []},
            {"pid": 200, "ppid": 100, "name": "orphan.exe", "path": "C:\\orphan", "command_line": "",
             "user": "u", "start_time": "2026-07-12T09:32:00", "threads": 3, "connections": []},
        ]
        # 单根：pid1 为根，pid100 是 pid1 的子，pid200 是 pid100 的子。
        abnormal_pids = {100, 200}
        pid_to_info = {
            100: {"risk_score": 70, "matched_rules": [{"name": "zombie_process"}],
                  "attack_path": None, "severity": "high", "parent_name": "System"},
            200: {"risk_score": 50, "matched_rules": [{"name": "orphan_process"}],
                  "attack_path": "explorer.exe → orphan.exe", "severity": "medium"},
        }
        result = ProcessTreeBuilder.build(processes, abnormal_pids, pid_to_info, enrich=True)
        return result

    def test_old_fields_preserved(self):
        result = self._build()
        self.assertEqual(result["name"], "System")
        self.assertEqual(result["pid"], 1)
        self.assertTrue(result["children"][0]["is_abnormal"])

    def test_root_enrich_fields(self):
        result = self._build()
        self.assertEqual(result["severity"], None)  # 正常进程无 severity
        self.assertEqual(result["parent_pid"], 0)
        self.assertEqual(result["parent_name"], "")
        self.assertEqual(result["start_time"], "2026-07-12T09:30:01")
        self.assertEqual(result["user"], "SYSTEM")
        self.assertEqual(result["threads"], 5)
        self.assertEqual(result["status"], "运行中")
        self.assertEqual(len(result["connections"]), 1)
        self.assertEqual(result["session"], "")
        self.assertEqual(result["attack_chain_step"], None)
        self.assertEqual(result["attack_chain_total"], None)

    def test_abnormal_node_severity_and_parent(self):
        result = self._build()
        cmd = result["children"][0]
        self.assertEqual(cmd["pid"], 100)
        # severity 取异常表
        self.assertEqual(cmd["severity"], "high")
        # parent_name 异常优先取异常表 parent_name
        self.assertEqual(cmd["parent_name"], "System")
        self.assertEqual(cmd["parent_pid"], 1)
        # threads==0 但无僵尸 state → 运行中（threads 不再用于判状态）
        self.assertEqual(cmd["threads"], 0)
        self.assertEqual(cmd["status"], "运行中")

    def test_child_node_parent_name_derived(self):
        result = self._build()
        # pid200 是 pid100 的子；异常表无 parent_name → 由 ppid 推导为父进程名 cmd.exe
        orphan = result["children"][0]["children"][0]
        self.assertEqual(orphan["pid"], 200)
        self.assertEqual(orphan["parent_pid"], 100)
        self.assertEqual(orphan["parent_name"], "cmd.exe")
        self.assertEqual(orphan["severity"], "medium")

    def test_orphan_ppid_missing_falls_back_to_empty(self):
        # 直接验证 _build_enrich_fields：ppid 不在 pid_to_proc 时 parent_name 兜底 ""
        from app.analysis.process_tree_builder import ProcessTreeBuilder
        fields = ProcessTreeBuilder._build_enrich_fields(
            {"ppid": 999}, {}, False, {1: {"name": "System"}}, None, "x"
        )
        self.assertEqual(fields["parent_pid"], 999)
        self.assertEqual(fields["parent_name"], "")

    def test_attack_chain_parsed_from_real_format(self):
        result = self._build()
        orphan = result["children"][0]["children"][0]
        # attack_path = "explorer.exe → orphan.exe" → total=2, step=2 (orphan.exe)
        self.assertEqual(orphan["attack_chain_total"], 2)
        self.assertEqual(orphan["attack_chain_step"], 2)


# ─────────────────────────────────────────────────────────────────────────────
# 3. _parse_attack_chain 解析器健壮性
# ─────────────────────────────────────────────────────────────────────────────

class TestParseAttackChain(unittest.TestCase):
    def _parse(self, path, name):
        from app.analysis.process_tree_builder import ProcessTreeBuilder
        return ProcessTreeBuilder._parse_attack_chain(path, name)

    def test_real_format_name_chain(self):
        # 真实代码库格式：进程名用 " → " 连接
        path = "explorer.exe → WINWORD.EXE → powershell.exe → cmd.exe → certutil.exe"
        self.assertEqual(self._parse(path, "WINWORD.EXE"), (2, 5))
        self.assertEqual(self._parse(path, "certutil.exe"), (5, 5))
        self.assertEqual(self._parse(path, "powershell.exe"), (3, 5))

    def test_real_format_case_insensitive(self):
        path = "explorer.exe → WINWORD.EXE → powershell.exe"
        # 大小写不敏感匹配
        self.assertEqual(self._parse(path, "winword.exe"), (2, 3))

    def test_convention_n_m(self):
        # 约定 A："N/M"
        self.assertEqual(self._parse("2/4", "x"), (2, 4))
        self.assertEqual(self._parse(" 1 / 3 ", "x"), (1, 3))

    def test_convention_list(self):
        # 约定 B：list of names
        self.assertEqual(self._parse(["a", "b", "c"], "b"), (2, 3))
        # JSON 数组字符串
        self.assertEqual(self._parse('["a", "B", "c"]', "b"), (2, 3))

    def test_fallback_parent_name_format(self):
        # anomaly_detector 回退格式："parent_name → name"
        self.assertEqual(self._parse("explorer.exe → notepad.exe", "notepad.exe"), (2, 2))

    def test_empty_none(self):
        self.assertEqual(self._parse(None, "x"), (None, None))
        self.assertEqual(self._parse("", "x"), (None, None))
        self.assertEqual(self._parse([], "x"), (None, None))

    def test_step_not_found_returns_total_without_step(self):
        # 当前进程名不在链中 → step=None，但 total 已知（合理降级）
        path = "explorer.exe → WINWORD.EXE"
        step, total = self._parse(path, "missing.exe")
        self.assertIsNone(step)
        self.assertEqual(total, 2)

    def test_non_string_garbage(self):
        self.assertEqual(self._parse(123, "x"), (None, None))
        self.assertEqual(self._parse({"a": 1}, "x"), (None, None))


# ─────────────────────────────────────────────────────────────────────────────
# 4. 虚拟根 + 循环引用节点 enrich 缺省字段
# ─────────────────────────────────────────────────────────────────────────────

class TestEnrichEdgeNodes(unittest.TestCase):
    def test_virtual_root_enrich_defaults(self):
        from app.analysis.process_tree_builder import ProcessTreeBuilder
        processes = [
            {"pid": 1, "ppid": 0, "name": "A"},
            {"pid": 2, "ppid": 0, "name": "B"},
        ]
        result = ProcessTreeBuilder.build(processes, set(), {}, enrich=True)
        self.assertEqual(result["name"], "All Processes")
        self.assertEqual(result["severity"], None)
        self.assertEqual(result["parent_pid"], 0)
        self.assertEqual(result["parent_name"], "")
        self.assertEqual(result["status"], "运行中")
        self.assertEqual(result["session"], "")
        self.assertEqual(result["attack_chain_step"], None)

    def test_circular_node_enrich_defaults(self):
        from app.analysis.process_tree_builder import ProcessTreeBuilder
        pid_to_proc = {
            100: {"pid": 100, "name": "ProcA", "path": "", "command_line": "", "ppid": 200,
                  "start_time": "", "user": "", "threads": 1, "connections": []},
            200: {"pid": 200, "name": "ProcB", "path": "", "command_line": "",
                  "ppid": 100, "start_time": "", "user": "", "threads": 1, "connections": []},
        }
        pid_to_children = {
            100: [{"pid": 200, "ppid": 100, "name": "ProcB"}],
            200: [{"pid": 100, "ppid": 200, "name": "ProcA"}],
        }
        node = ProcessTreeBuilder._build_tree_recursive(
            100, pid_to_proc, pid_to_children, set(), {}, set(), True
        )
        circular = node["children"][0]["children"][0]
        self.assertIn("(circular reference)", circular["name"])
        # enrich 字段存在（循环节点也应带来增强字段，保证下游健壮）
        self.assertIn("severity", circular)
        self.assertIn("parent_pid", circular)
        self.assertEqual(circular["attack_chain_step"], None)


# ─────────────────────────────────────────────────────────────────────────────
# 5. status 派生修正回归：仅 state ∈ {z, zombie, defunct} → 疑似僵尸
#    threads==0 / 缺失 不再触发，避免回退采集环境误报
# ─────────────────────────────────────────────────────────────────────────────

class TestEnrichStatusZombieDerivation(unittest.TestCase):
    """status 状态派生修正回归.

    规则：仅当 proc 显式 state ∈ {z, zombie, defunct} 时为 "疑似僵尸"，
    其余（含 threads==0、state 缺失或非僵尸状态）均为 "运行中"。
    """

    def _status_of(self, proc):
        from app.analysis.process_tree_builder import ProcessTreeBuilder
        fields = ProcessTreeBuilder._build_enrich_fields(
            proc, {}, False, {}, None, proc.get("name", "x")
        )
        return fields["status"], fields["threads"]

    def test_zombie_state_lowercase(self):
        # (a) state="zombie"（threads=0）→ 疑似僵尸
        status, threads = self._status_of({"name": "p", "threads": 0, "state": "zombie"})
        self.assertEqual(threads, 0)
        self.assertEqual(status, "疑似僵尸")

    def test_z_state_upper(self):
        # (b) state="Z" → 疑似僵尸
        status, _ = self._status_of({"name": "p", "threads": 0, "state": "Z"})
        self.assertEqual(status, "疑似僵尸")

    def test_defunct_state(self):
        # (c) state="defunct" → 疑似僵尸
        status, _ = self._status_of({"name": "p", "threads": 0, "state": "defunct"})
        self.assertEqual(status, "疑似僵尸")

    def test_threads_zero_no_state_is_running(self):
        # (d) threads=0、无 state 键 → 运行中
        status, threads = self._status_of({"name": "p", "threads": 0})
        self.assertEqual(threads, 0)
        self.assertEqual(status, "运行中")

    def test_threads_missing_no_state_is_running(self):
        # (e) threads 键不存在、无 state → 运行中（threads 缺省 0，但仍运行中）
        status, threads = self._status_of({"name": "p"})
        self.assertEqual(threads, 0)
        self.assertEqual(status, "运行中")

    def test_threads_positive_no_state_is_running(self):
        # (f) threads>0、无 state → 运行中
        status, threads = self._status_of({"name": "p", "threads": 8})
        self.assertEqual(threads, 8)
        self.assertEqual(status, "运行中")


if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite)
