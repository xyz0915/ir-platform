"""独立 QA 验证 —— 进程树「疑似僵尸」误报修复的边界用例（不覆盖工程师文件）.

本文件由 QA（严过关）独立撰写，专门覆盖任务规定的 (a)-(h) 边界，
用于独立验证工程师寇豆码对 ``process_tree_builder._build_enrich_fields`` 的修复：

修复前（bug）：``status = "疑似僵尸" if threads == 0 else "运行中"``
  → 回退采集环境（wmic/tasklist）把每个进程 threads 写死为 0，导致全员误报。

修复后（待验证）：
  ``state = (proc.get("state") or "").strip().lower()``
  ``status = "疑似僵尸" if state in ("z", "zombie", "defunct") else "运行中"``
  ``threads`` 仍存入节点，但不再驱动 status。

覆盖：
(a) enrich=True，节点 state="zombie" 且 threads=0 → status=="疑似僵尸"
(b) state="Z" / state="defunct" 同理 → 疑似僵尸
(c) state="running"（正常状态字面值）→ 运行中
(d) 节点无 state 键且 threads=0 → 运行中  ← 关键：旧的误报路径不再触发
(e) 节点 threads 键缺失（key 不存在）且无 state → 运行中
(f) 节点 threads=5 且无 state → 运行中
(g) 异常进程（在 abnormal_pids 中）但无僵尸 state → status 仍按 state 判为运行中
(h) 虚拟根（多根场景）status 仍为"运行中"

并附加健壮性用例：
- state 含前后空格 + 大小写混合（" ZOMBIE "）→ 疑似僵尸（strip+lower 生效）
- threads 字段始终被存入节点（无论状态）
- 异常进程且 state="zombie" → 疑似僵尸（status 由 state 唯一决定，与 is_abnormal 正交）
"""

import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.analysis.process_tree_builder import ProcessTreeBuilder


ZOMBIE = "疑似僵尸"
RUNNING = "运行中"


def _find_node(tree, pid):
    """深度优先查找 pid 对应节点（找不到返回 None）。"""
    if tree.get("pid") == pid:
        return tree
    for child in tree.get("children", []) or []:
        res = _find_node(child, pid)
        if res is not None:
            return res
    return None


def _build_single(proc, abnormal_pids=None, pid_to_info=None):
    """以单根进程构建 enrich 树，返回根节点。"""
    abnormal_pids = abnormal_pids or set()
    pid_to_info = pid_to_info or {}
    return ProcessTreeBuilder.build([proc], abnormal_pids, pid_to_info, enrich=True)


class TestZombieStatusBoundary(unittest.TestCase):
    # (a) state="zombie" 且 threads=0 → 疑似僵尸
    def test_a_state_zombie_threads_zero_is_zombie(self):
        proc = {"pid": 1, "ppid": 0, "name": "proc1", "state": "zombie", "threads": 0}
        node = _build_single(proc)
        self.assertEqual(node["status"], ZOMBIE)
        self.assertEqual(node["threads"], 0)  # threads 仍存入节点

    # (b) state="Z" / state="defunct" → 疑似僵尸
    def test_b_other_zombie_states(self):
        for state in ("Z", "defunct"):
            with self.subTest(state=state):
                proc = {"pid": 1, "ppid": 0, "name": "proc", "state": state, "threads": 0}
                node = _build_single(proc)
                self.assertEqual(node["status"], ZOMBIE)

    # (c) state="running"（正常状态字面值）→ 运行中
    def test_c_normal_state_literal_is_running(self):
        proc = {"pid": 1, "ppid": 0, "name": "proc", "state": "running", "threads": 0}
        node = _build_single(proc)
        self.assertEqual(node["status"], RUNNING)

    # (d) 无 state 键 且 threads=0 → 运行中（旧的误报路径不再触发）
    def test_d_no_state_key_threads_zero_is_running(self):
        proc = {"pid": 1, "ppid": 0, "name": "proc", "threads": 0}
        node = _build_single(proc)
        self.assertEqual(node["status"], RUNNING)

    # (e) threads 键缺失（key 不存在）且无 state → 运行中
    def test_e_threads_key_missing_no_state_is_running(self):
        proc = {"pid": 1, "ppid": 0, "name": "proc"}
        node = _build_single(proc)
        self.assertEqual(node["status"], RUNNING)
        # threads 键缺失时应回退为 0 并存入节点
        self.assertIn("threads", node)
        self.assertEqual(node["threads"], 0)

    # (f) threads=5 且无 state → 运行中
    def test_f_threads_five_no_state_is_running(self):
        proc = {"pid": 1, "ppid": 0, "name": "proc", "threads": 5}
        node = _build_single(proc)
        self.assertEqual(node["status"], RUNNING)
        self.assertEqual(node["threads"], 5)

    # (g) 异常进程（abnormal_pids 中）但无僵尸 state → 仍按 state 判为运行中
    def test_g_abnormal_process_without_zombie_state_is_running(self):
        proc = {"pid": 9, "ppid": 0, "name": "evil", "state": "running", "threads": 0}
        info = {
            9: {
                "severity": "high",
                "risk_score": 90,
                "matched_rules": ["suspicious_child"],
                "attack_path": None,
                "parent_name": "",
            }
        }
        node = _build_single(proc, abnormal_pids={9}, pid_to_info=info)
        self.assertTrue(node["is_abnormal"])
        self.assertEqual(node["severity"], "high")
        # 关键点：即使异常进程，只要非僵尸 state，status 必须仍是"运行中"
        self.assertEqual(node["status"], RUNNING)

    # (h) 虚拟根（多根场景）status 仍为"运行中"
    def test_h_virtual_root_status_running(self):
        procs = [
            {"pid": 1, "ppid": 0, "name": "a", "threads": 0},
            {"pid": 2, "ppid": 0, "name": "b", "threads": 0},
        ]
        tree = ProcessTreeBuilder.build(procs, set(), {}, enrich=True)
        # 多根 → 包裹在虚拟根 "All Processes" 中
        self.assertEqual(tree["name"], "All Processes")
        self.assertEqual(tree["status"], RUNNING)
        # 各真实子节点默认也为运行中
        for child in tree.get("children", []):
            self.assertEqual(child["status"], RUNNING)

    # 健壮性：state 含前后空格 + 大小写混合 → 疑似僵尸（strip+lower 生效）
    def test_robust_state_whitespace_and_case(self):
        for raw in (" ZOMBIE ", "Zombie", "  DEFUNCT ", "z"):
            with self.subTest(raw=raw):
                proc = {"pid": 1, "ppid": 0, "name": "p", "state": raw, "threads": 0}
                node = _build_single(proc)
                self.assertEqual(node["status"], ZOMBIE)

    # 健壮性：异常进程且 state="zombie" → 疑似僵尸（status 与 is_abnormal 正交）
    def test_robust_abnormal_with_zombie_state_is_zombie(self):
        proc = {"pid": 7, "ppid": 0, "name": "z", "state": "zombie", "threads": 0}
        info = {7: {"severity": "critical", "risk_score": 99,
                     "matched_rules": ["zombie"], "attack_path": None}}
        node = _build_single(proc, abnormal_pids={7}, pid_to_info=info)
        self.assertTrue(node["is_abnormal"])
        self.assertEqual(node["status"], ZOMBIE)

    # 直接调用 _build_enrich_fields 的单元级校验（不依赖完整树）
    def test_unit_enrich_fields_status_logic(self):
        # threads=0 且无 state → 运行中（旧 bug 即在此处误报）
        fields = ProcessTreeBuilder._build_enrich_fields(
            {"ppid": 0, "threads": 0}, {}, False, {}, None, "x"
        )
        self.assertEqual(fields["status"], RUNNING)
        self.assertEqual(fields["threads"], 0)

        fields2 = ProcessTreeBuilder._build_enrich_fields(
            {"ppid": 0, "state": "zombie", "threads": 0}, {}, False, {}, None, "x"
        )
        self.assertEqual(fields2["status"], ZOMBIE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
