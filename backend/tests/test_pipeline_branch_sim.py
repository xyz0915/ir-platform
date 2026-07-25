"""分支模拟 BFS 图计算（Phase 3 / BRANCH-01）单元测试。

覆盖 agent_management.compute_branch_paths 的：
- 选择分支后正确计算 active / pruned 下游
- 未指定 chosen_branch 时默认取 branches[0]
- 无 branches 时返回空 active
- 共享子树下 pruned 不应包含 active 节点
- chosen_target 与 pruned_edges 正确

（纯图计算，不触 DB / 不执行下游节点）
"""
import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))


def _compute(*args, **kwargs):
    from app.api.agent_management import compute_branch_paths
    return compute_branch_paths(*args, **kwargs)


class TestComputeBranchPaths(unittest.TestCase):
    """compute_branch_paths BFS 行为测试。"""

    def test_chosen_branch_produces_active_and_pruned(self):
        """选择 A 分支：active={n-a,n-c}，pruned={n-b,n-d}，pruned_edges 命中 n-b 出发边。"""
        branches = [
            {"label": "A", "target": "n-a"},
            {"label": "B", "target": "n-b"},
        ]
        connections = [
            {"sourceId": "n-a", "targetId": "n-c"},
            {"sourceId": "n-b", "targetId": "n-d"},
        ]
        res = _compute("branch1", branches, "A", connections)
        self.assertEqual(res["chosen_target"], "n-a")
        self.assertEqual(res["active_nodes"], ["n-a", "n-c"])
        self.assertEqual(res["pruned_nodes"], ["n-b", "n-d"])
        self.assertEqual(
            res["pruned_edges"], [{"sourceId": "n-b", "targetId": "n-d"}]
        )
        self.assertEqual(res["downstream_active_count"], 2)

    def test_chosen_none_yields_empty_active(self):
        """compute_branch_paths 自身不默认 chosen_branch（默认由端点处理）：
        None 入参原样返回，chosen_target 为 None → active 为空。"""
        branches = [
            {"label": "A", "target": "n-a"},
            {"label": "B", "target": "n-b"},
        ]
        connections = [{"sourceId": "n-a", "targetId": "n-c"}]
        res = _compute("b", branches, None, connections)
        self.assertIsNone(res["chosen_branch"])
        self.assertEqual(res["active_nodes"], [])

    def test_endpoint_defaults_chosen_to_first_branch(self):
        """simulate_branch_endpoint 缺省 chosen_branch 时应默认取 branches[0].label。"""
        from app.api.agent_management import simulate_branch_endpoint
        data = {
            "node_name": "b",
            "branches": [
                {"label": "A", "target": "n-a"},
                {"label": "B", "target": "n-b"},
            ],
            "connections": [{"sourceId": "n-a", "targetId": "n-c"}],
        }
        resp = simulate_branch_endpoint(data)
        self.assertEqual(resp["code"], 0)  # _ok 信封
        self.assertEqual(resp["data"]["chosen_branch"], "A")
        self.assertEqual(resp["data"]["active_nodes"], ["n-a", "n-c"])

    def test_no_branches_returns_empty_active(self):
        """branches 为空时，active / pruned / pruned_edges 全空。"""
        res = _compute(
            "b", [], None, [{"sourceId": "n-x", "targetId": "n-y"}]
        )
        self.assertEqual(res["active_nodes"], [])
        self.assertEqual(res["pruned_nodes"], [])
        self.assertEqual(res["pruned_edges"], [])

    def test_pruned_excludes_active_shared_subtree(self):
        """A→n-a→n-shared；B→n-b→n-shared：共享下游 n-shared 应归 active，不出现在 pruned。"""
        branches = [
            {"label": "A", "target": "n-a"},
            {"label": "B", "target": "n-b"},
        ]
        connections = [
            {"sourceId": "n-a", "targetId": "n-shared"},
            {"sourceId": "n-b", "targetId": "n-shared"},
        ]
        res = _compute("b", branches, "A", connections)
        self.assertIn("n-shared", res["active_nodes"])
        self.assertNotIn("n-shared", res["pruned_nodes"])
        self.assertEqual(res["pruned_nodes"], ["n-b"])


if __name__ == "__main__":
    unittest.main()
