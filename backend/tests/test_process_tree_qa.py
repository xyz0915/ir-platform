"""进程树 enrich —— QA 独立边界用例（严过关）.

不重复工程师的 test_process_tree_enrich.py，而是针对「增量增强」的红线与
易错边界做补充验证：

(a) enrich=False 时，任一节点 dict **绝不**包含 11 个新键（向后兼容铁证）。
(b) enrich=True 时，正常进程（非异常）severity=None、attack_chain=(None,None)、
    status 依 proc.state 推导（仅 z/zombie/defunct → 疑似僵尸）。
(c) attack_path 真实链格式：step=当前进程名在链中的 1-based 位置，total=链长。
(d) orphan 进程（ppid 不在列表）仍带 parent_name 兜底（字段存在，值为 ""）。
(e) 循环引用节点：增强字段不缺失，且不爆栈（无 RecursionError）。
(f) session 恒为 "" 降级（覆盖根/子/虚拟根/循环节点）。

额外回归护栏：
(g) enrich=True 仅追加**恰好** 11 个键，且不覆盖任何旧字段。
(h) enrich 字段来源正确（parent_pid 取自 ppid；connections 透传 proc）。
"""

import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.analysis.process_tree_builder import ProcessTreeBuilder

# 增量增强的 11 个字段（与设计文档 / QA 任务书一致）
ENRICH_KEYS = {
    "severity", "parent_pid", "parent_name", "start_time", "user",
    "threads", "status", "connections", "attack_chain_step",
    "attack_chain_total", "session",
}

# 历史版本的旧字段（enrich 不得破坏）
OLD_KEYS = {"name", "pid", "process_name", "process_path", "command_line",
            "is_abnormal", "risk_score", "matched_rules", "attack_path", "children"}


def _walk(node, acc):
    """递归收集子树中所有节点 dict。"""
    if isinstance(node, dict):
        acc.append(node)
        for c in node.get("children", []) or []:
            _walk(c, acc)


# ─────────────────────────────────────────────────────────────────────────────
# (a) enrich=False 绝不出现 11 个新键（向后兼容铁证）
# ─────────────────────────────────────────────────────────────────────────────

class TestEnrichFalseHasNoNewKeys(unittest.TestCase):
    def _build_default(self, processes):
        return ProcessTreeBuilder.build(processes, set(), {})

    def test_single_root_no_enrich_keys_anywhere(self):
        processes = [
            {"pid": 1, "ppid": 0, "name": "System", "threads": 5, "connections": []},
            {"pid": 100, "ppid": 1, "name": "cmd.exe", "threads": 0, "connections": [{"remote_address": "1.2.3.4"}]},
            {"pid": 200, "ppid": 100, "name": "powershell.exe", "threads": 3, "connections": []},
        ]
        tree = self._build_default(processes)
        nodes = []
        _walk(tree, nodes)
        self.assertGreaterEqual(len(nodes), 3)
        for n in nodes:
            overlap = set(n.keys()) & ENRICH_KEYS
            self.assertEqual(overlap, set(), f"enrich=False 出现了新键: {overlap}")

    def test_virtual_root_no_enrich_keys(self):
        # 多根 → 虚拟根 "All Processes"
        processes = [
            {"pid": 1, "ppid": 0, "name": "A", "threads": 1, "connections": []},
            {"pid": 2, "ppid": 0, "name": "B", "threads": 1, "connections": []},
        ]
        tree = self._build_default(processes)
        self.assertEqual(tree["name"], "All Processes")
        nodes = []
        _walk(tree, nodes)
        for n in nodes:
            self.assertEqual(set(n.keys()) & ENRICH_KEYS, set())

    def test_legacy_three_arg_call_compat(self):
        # 仅 3 个位置参数调用（旧调用方）不应抛错且不含新键
        tree = ProcessTreeBuilder.build([{"pid": 1, "ppid": 0, "name": "X"}], set(), {})
        self.assertEqual(set(tree.keys()) & ENRICH_KEYS, set())


# ─────────────────────────────────────────────────────────────────────────────
# (b) enrich=True 正常进程：severity=None、attack_chain=(None,None)、status 依 proc.state（仅 z/zombie/defunct → 疑似僵尸）
# ─────────────────────────────────────────────────────────────────────────────

class TestEnrichTrueNormalNode(unittest.TestCase):
    def _build(self):
        processes = [
            {"pid": 1, "ppid": 0, "name": "System", "threads": 5, "connections": []},
            {"pid": 100, "ppid": 1, "name": "svchost.exe", "threads": 0, "connections": []},
            {"pid": 200, "ppid": 100, "name": "powershell.exe", "threads": 3, "connections": []},
        ]
        # 无异常进程
        return ProcessTreeBuilder.build(processes, set(), {}, enrich=True)

    def test_all_normal_nodes_severity_none(self):
        tree = self._build()
        nodes = []
        _walk(tree, nodes)
        for n in nodes:
            self.assertIsNone(n["severity"])
            self.assertIsNone(n["attack_chain_step"])
            self.assertIsNone(n["attack_chain_total"])

    def test_status_derived_from_state(self):
        tree = self._build()
        root = tree                       # threads=5、无 state → 运行中
        child = tree["children"][0]      # threads=0、无 state → 运行中（threads 不再判状态）
        grand = child["children"][0]     # threads=3、无 state → 运行中
        self.assertEqual(root["status"], "运行中")
        self.assertEqual(child["status"], "运行中")
        self.assertEqual(grand["status"], "运行中")


# ─────────────────────────────────────────────────────────────────────────────
# (c) attack_path 真实链格式：step=当前进程名位置，total=链长
# ─────────────────────────────────────────────────────────────────────────────

class TestAttackChainRealFormat(unittest.TestCase):
    def _build(self, attack_path, proc_name, pid=200):
        processes = [
            {"pid": 1, "ppid": 0, "name": "System", "threads": 1, "connections": []},
            {"pid": 100, "ppid": 1, "name": "explorer.exe", "threads": 1, "connections": []},
            {"pid": pid, "ppid": 100, "name": proc_name, "threads": 1, "connections": []},
        ]
        abnormal_pids = {pid}
        pid_to_info = {pid: {"risk_score": 50, "matched_rules": [{"name": "x"}],
                             "attack_path": attack_path, "severity": "medium"}}
        return ProcessTreeBuilder.build(processes, abnormal_pids, pid_to_info, enrich=True)

    def test_middle_of_chain(self):
        # explorer.exe → WINWORD.EXE → powershell.exe → cmd.exe → certutil.exe
        # 当前进程=WINWORD.EXE → step=2, total=5
        tree = self._build(
            "explorer.exe → WINWORD.EXE → powershell.exe → cmd.exe → certutil.exe",
            "WINWORD.EXE",
        )
        node = tree["children"][0]["children"][0]
        self.assertEqual(node["attack_chain_step"], 2)
        self.assertEqual(node["attack_chain_total"], 5)
        self.assertEqual(node["severity"], "medium")

    def test_three_chain_last_position(self):
        # a → b → c，当前进程=c → step=3, total=3
        tree = self._build("a → b → c", "c")
        node = tree["children"][0]["children"][0]
        self.assertEqual(node["attack_chain_step"], 3)
        self.assertEqual(node["attack_chain_total"], 3)

    def test_case_insensitive_position(self):
        tree = self._build("explorer.exe → WINWORD.EXE → powershell.exe", "winword.exe")
        node = tree["children"][0]["children"][0]
        self.assertEqual(node["attack_chain_step"], 2)


# ─────────────────────────────────────────────────────────────────────────────
# (d) orphan 进程（ppid 不在列表）仍带 parent_name 兜底
# ─────────────────────────────────────────────────────────────────────────────

class TestOrphanParentNameFallback(unittest.TestCase):
    def test_orphan_has_parent_name_field_fallback(self):
        # ppid=999 不在进程列表中 → orphan，name 标注 "(orphan process)"
        processes = [
            {"pid": 1, "ppid": 0, "name": "System", "threads": 1, "connections": []},
            {"pid": 5, "ppid": 999, "name": "orphan.exe", "threads": 2, "connections": []},
        ]
        tree = ProcessTreeBuilder.build(processes, set(), {}, enrich=True)

        # 多根场景会包裹为虚拟根 "All Processes"，orphan 是其直接子节点之一
        def _find_by_pid(n, target):
            if n.get("pid") == target:
                return n
            for c in n.get("children", []) or []:
                r = _find_by_pid(c, target)
                if r:
                    return r
            return None

        orphan = _find_by_pid(tree, 5)
        self.assertIsNotNone(orphan, "未在树中找到 orphan 节点")
        self.assertIn("(orphan process)", orphan["name"])
        self.assertIn("parent_pid", orphan)
        self.assertEqual(orphan["parent_pid"], 999)
        # 父进程不在列表 → parent_name 兜底为 ""
        self.assertIn("parent_name", orphan)
        self.assertEqual(orphan["parent_name"], "")
        # 其它增强字段仍齐全
        for k in ENRICH_KEYS:
            self.assertIn(k, orphan)


# ─────────────────────────────────────────────────────────────────────────────
# (e) 循环引用节点：增强字段不缺失，且不爆栈
# ─────────────────────────────────────────────────────────────────────────────

class TestCircularNodeEnrichAndNoStackOverflow(unittest.TestCase):
    def test_deep_cycle_no_recursion_error_and_fields_present(self):
        pid_to_proc = {
            100: {"pid": 100, "name": "ProcA", "path": "", "command_line": "", "ppid": 200,
                  "start_time": "", "user": "", "threads": 1, "connections": []},
            200: {"pid": 200, "name": "ProcB", "path": "", "command_line": "", "ppid": 300,
                  "start_time": "", "user": "", "threads": 1, "connections": []},
            300: {"pid": 300, "name": "ProcC", "path": "", "command_line": "", "ppid": 400,
                  "start_time": "", "user": "", "threads": 1, "connections": []},
            400: {"pid": 400, "name": "ProcD", "path": "", "command_line": "", "ppid": 100,
                  "start_time": "", "user": "", "threads": 1, "connections": []},
        }
        # 构造闭环子节点关系：100->200->300->400->100
        pid_to_children = {
            100: [pid_to_proc[200]],
            200: [pid_to_proc[300]],
            300: [pid_to_proc[400]],
            400: [pid_to_proc[100]],
        }
        # 直接调用递归构建（与工程师一致），验证不爆栈且增强字段不缺失
        node = ProcessTreeBuilder._build_tree_recursive(
            100, pid_to_proc, pid_to_children, set(), {}, set(), True
        )
        self.assertEqual(node["name"], "ProcA")
        # 沿路径找到循环标记节点
        cur = node
        depth = 0
        circular = None
        while cur and depth < 10:
            kids = cur.get("children", []) or []
            if kids and "(circular reference)" in kids[0].get("name", ""):
                circular = kids[0]
                break
            cur = kids[0] if kids else None
            depth += 1
        self.assertIsNotNone(circular, "未找到循环引用标记节点")
        # 循环节点增强字段 11 个全在
        for k in ENRICH_KEYS:
            self.assertIn(k, circular, f"循环节点缺少增强字段 {k}")
        self.assertIsNone(circular["attack_chain_step"])
        self.assertIsNone(circular["severity"])

    def test_build_with_self_ref_ppid_does_not_hang(self):
        # 自引用 ppid（ppid==pid）不应导致无限递归，且安全返回
        processes = [{"pid": 100, "ppid": 100, "name": "self", "threads": 1, "connections": []}]
        tree = ProcessTreeBuilder.build(processes, set(), {}, enrich=True)
        # 自引用节点不是根（ppid 在列表内）→ 无根 → 返回 empty
        self.assertIn(tree["name"], ("(empty)",))


# ─────────────────────────────────────────────────────────────────────────────
# (f) session 恒为 "" 降级
# ─────────────────────────────────────────────────────────────────────────────

class TestSessionAlwaysEmpty(unittest.TestCase):
    def test_session_empty_on_all_node_types(self):
        # 普通树
        processes = [
            {"pid": 1, "ppid": 0, "name": "System", "threads": 1, "connections": []},
            {"pid": 100, "ppid": 1, "name": "cmd.exe", "threads": 1, "connections": []},
        ]
        tree = ProcessTreeBuilder.build(processes, set(), {}, enrich=True)
        nodes = []
        _walk(tree, nodes)
        for n in nodes:
            self.assertEqual(n["session"], "", f"session 未降级为空: {n.get('name')}")

    def test_session_empty_virtual_root(self):
        processes = [
            {"pid": 1, "ppid": 0, "name": "A", "threads": 1, "connections": []},
            {"pid": 2, "ppid": 0, "name": "B", "threads": 1, "connections": []},
        ]
        tree = ProcessTreeBuilder.build(processes, set(), {}, enrich=True)
        self.assertEqual(tree["session"], "")


# ─────────────────────────────────────────────────────────────────────────────
# (g) enrich=True 仅追加恰好 11 个键，且不覆盖旧字段
# ─────────────────────────────────────────────────────────────────────────────

class TestEnrichExactElevenKeysNoClobber(unittest.TestCase):
    def test_exactly_eleven_new_keys(self):
        processes = [
            {"pid": 1, "ppid": 0, "name": "System", "threads": 5, "connections": [{"remote_address": "8.8.8.8"}]},
            {"pid": 100, "ppid": 1, "name": "cmd.exe", "threads": 0, "connections": []},
        ]
        abnormal_pids = {100}
        pid_to_info = {100: {"risk_score": 70, "matched_rules": [{"name": "z"}],
                             "attack_path": "explorer.exe → cmd.exe", "severity": "high",
                             "parent_name": "System"}}
        tree = ProcessTreeBuilder.build(processes, abnormal_pids, pid_to_info, enrich=True)
        nodes = []
        _walk(tree, nodes)
        for n in nodes:
            new = set(n.keys()) & ENRICH_KEYS
            self.assertEqual(len(new), 11, f"节点 {n.get('name')} 新键数={len(new)}（应为11）")
            # 旧字段不被覆盖
            for ok in OLD_KEYS:
                self.assertIn(ok, n, f"节点 {n.get('name')} 缺失旧字段 {ok}")

    def test_parent_pid_and_connections_sourced_correctly(self):
        processes = [
            {"pid": 1, "ppid": 0, "name": "System", "threads": 1,
             "connections": [{"remote_address": "8.8.8.8", "remote_port": 53}]},
            {"pid": 100, "ppid": 1, "name": "cmd.exe", "threads": 1, "connections": []},
        ]
        tree = ProcessTreeBuilder.build(processes, set(), {}, enrich=True)
        self.assertEqual(tree["parent_pid"], 0)
        self.assertEqual(len(tree["connections"]), 1)
        self.assertEqual(tree["connections"][0]["remote_address"], "8.8.8.8")
        child = tree["children"][0]
        self.assertEqual(child["parent_pid"], 1)
        self.assertEqual(child["connections"], [])


# ─────────────────────────────────────────────────────────────────────────────
# (h) 异常进程 attack_chain 缺失进程名时的合理降级（step=None, total 已知）
# ─────────────────────────────────────────────────────────────────────────────

class TestAttackChainStepMissing(unittest.TestCase):
    def test_name_not_in_chain_step_none_total_known(self):
        processes = [
            {"pid": 1, "ppid": 0, "name": "System", "threads": 1, "connections": []},
            {"pid": 100, "ppid": 1, "name": "unknown_proc.exe", "threads": 1, "connections": []},
        ]
        abnormal_pids = {100}
        pid_to_info = {100: {"risk_score": 50, "matched_rules": [{"name": "x"}],
                             "attack_path": "explorer.exe → WINWORD.EXE", "severity": "medium"}}
        tree = ProcessTreeBuilder.build(processes, abnormal_pids, pid_to_info, enrich=True)
        node = tree["children"][0]
        # 当前进程名不在链中 → step=None，但 total=2 仍已知
        self.assertIsNone(node["attack_chain_step"])
        self.assertEqual(node["attack_chain_total"], 2)


if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite)
