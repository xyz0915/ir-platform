"""单节点调试（Phase 3 / KC-1）后端单元测试。

覆盖 PipelineEngine.execute_node 的：
- simulate 模式（返回 fixture，不触外部 IO）
- real 模式（file_analysis 无 host 时返回空结果；branch 真实执行体）
- 异常捕获（unsupported node_type → status=failed，不抛异常）
- 历史落库（debug-<hex> 前缀 + status='debug'，list_debug_runs_by_node 可查）
- _resolve_host_id 两段式

测试库：临时 SQLite（settings.DB_PATH + init_db），不污染生产库。
"""
import asyncio
import sys
import unittest
import uuid
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

# 每次运行使用独立 DB 文件名，避免沙箱环境下 unlink（safe-delete）不可用的问题。
TEST_DB_PATH = str(BACKEND_DIR / "data" / f"test_pipeline_node_debug_{uuid.uuid4().hex[:8]}.db")


class TestExecuteNode(unittest.TestCase):
    """PipelineEngine.execute_node 行为测试。"""

    @classmethod
    def setUpClass(cls):
        """建立临时测试库并初始化表结构（唯一文件名，best-effort 清旧库）。"""
        db_path = Path(TEST_DB_PATH)
        if db_path.exists():
            try:
                db_path.unlink()
            except OSError:
                # 沙箱 safe-delete 不可用时沿用既有库（schema 稳定，测试用具容错）
                pass
        from app.config import settings
        settings.DB_PATH = TEST_DB_PATH
        Path(settings.DATA_DIR).mkdir(parents=True, exist_ok=True)
        from app.database import init_db
        init_db()

    def setUp(self):
        """每个用例使用独立引擎实例。"""
        from app.services.agents.pipeline_engine import PipelineEngine
        self.engine = PipelineEngine()

    def _run(self, **kwargs):
        """同步包装异步 execute_node。"""
        return asyncio.run(self.engine.execute_node(**kwargs))

    # ── simulate 模式 ──
    def test_simulate_file_analysis_returns_fixture(self):
        """simulate 模式应返回与 fixture 同构的结果，且 run_id 前缀 debug-。"""
        res = self._run(
            node_type="file_analysis",
            node_name="file_analysis",
            input_params={},
            context_vars={},
            mode="simulate",
            user={},
        )
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["node_type"], "file_analysis")
        self.assertIn("文件分析", res["output_text"])
        self.assertIn("files", res["result"]["structured"])
        self.assertTrue(res["run_id"].startswith("debug-"))

    def test_simulate_persists_debug_run(self):
        """simulate 执行应落库，且 list_debug_runs_by_node 可按 node_name + mode 查到。"""
        res = self._run(
            node_type="registry_analysis",
            node_name="registry_analysis",
            input_params={},
            context_vars={"host_id": "host-sim-1"},
            mode="simulate",
            user={},
        )
        run_id = res["run_id"]
        self.assertIsNotNone(run_id)
        from app.models.agent_run import NodeRunRepository
        items = NodeRunRepository.list_debug_runs_by_node(
            node_name="registry_analysis", mode="simulate"
        )
        self.assertTrue(any(it["run_id"] == run_id for it in items))
        found = next(it for it in items if it["run_id"] == run_id)
        self.assertEqual(found["status"], "success")
        self.assertEqual(found["mode"], "simulate")
        self.assertEqual(found["input"]["resolved_host_id"], "host-sim-1")

    # ── real 模式 ──
    def test_real_file_analysis_no_host_returns_empty(self):
        """real 模式无 host_id 时返回空结果（不报错，status=success）。"""
        res = self._run(
            node_type="file_analysis",
            node_name="file_analysis",
            input_params={},
            context_vars={},
            mode="real",
            user={},
        )
        self.assertEqual(res["status"], "success")
        self.assertIn("未检测到", res["output_text"])
        self.assertEqual(res["result"]["structured"]["count"], 0)

    def test_real_branch_executes_with_chosen(self):
        """real 模式 branch 节点应执行 _run_branch 并回显 chosen_branch / downstream_active。"""
        res = self._run(
            node_type="branch",
            node_name="branch_demo",
            input_params={
                "branches": [
                    {"label": "A", "target": "t-a"},
                    {"label": "B", "target": "t-b"},
                ],
                "chosen_branch": "A",
            },
            context_vars={},
            mode="real",
            user={},
        )
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["result"]["structured"]["chosen_branch"], "A")
        self.assertEqual(res["result"]["structured"]["downstream_active"], ["t-a"])

    # ── 异常路径 ──
    def test_unsupported_node_type_fails_gracefully(self):
        """不支持的 node_type（real 模式）应结构化返回 failed，不向上抛异常。"""
        res = self._run(
            node_type="no_such_type",
            node_name="no_such_type",
            input_params={},
            context_vars={},
            mode="real",
            user={},
        )
        self.assertEqual(res["status"], "failed")
        self.assertTrue(res["error"])
        self.assertIsNone(res["output_text"] or None)
        self.assertIsNotNone(res["run_id"])  # 失败仍落库，便于回溯

    # ── _resolve_host_id 两段式 ──
    def test_resolve_host_id_prefers_host_id(self):
        self.assertEqual(self.engine._resolve_host_id({"host_id": "h-1"}), "h-1")

    def test_resolve_host_id_empty_returns_none(self):
        self.assertIsNone(self.engine._resolve_host_id({}))
        self.assertIsNone(self.engine._resolve_host_id(None))


if __name__ == "__main__":
    unittest.main()
