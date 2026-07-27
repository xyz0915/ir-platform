"""单节点调试 — 触发器（trigger）节点分诊后端单元测试（KC-1 解耦扩展）。

覆盖 PipelineEngine.execute_node 在 node_type='trigger' 时的：
- simulate 模式：返回 SIMULATE_TRIAGE fixture（含 P0/P1、confidence>0、stage='triage'）
- real 模式：调用 TriageAgent 对 SE-1 做真实分诊（status=success、output 非空、confidence>0，
  不依赖 LLM 内容，降级仍成功）
- 缺失 event_id：返回 status=failed 且 output 含友好提示，不抛异常（不返回 500）

测试库：临时 SQLite（settings.DB_PATH + init_db），不污染生产库。
"""
import asyncio
import json
import sys
import unittest
import uuid
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

# 每次运行使用独立 DB 文件名，避免沙箱环境下 unlink（safe-delete）不可用的问题。
TEST_DB_PATH = str(BACKEND_DIR / "data" / f"test_pipeline_node_triage_{uuid.uuid4().hex[:8]}.db")


def seed_full_incident():
    """构造一个完整事件（SE-1：critical malware + 关联日志 + 规则）。

    供 real 模式分诊测试使用，确保 TriageAgent 能基于真实数据产出结论。
    """
    from app.database import get_connection
    with get_connection() as conn:
        conn.execute("INSERT INTO cases (name) VALUES ('qa_case')")
        case_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO hosts (case_id, hostname, ip_address, os_type) "
            "VALUES (?, 'QAHOST', '10.0.0.7', 'Windows')", (case_id,))
        host_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO security_events "
            "(id, timestamp, host_id, event_type, event_key, severity, ai_verdict) "
            "VALUES (?, '2026-07-18 10:00:00', ?, 'malware', 'ek1', 'critical', ?)",
            ("SE-1", host_id, json.dumps({"label": "suspicious", "reason": "beacon"})))
        conn.execute(
            "INSERT INTO normalized_logs "
            "(host_id, log_source, event_type, event_label, severity, timestamp, "
            "source_ip, process_name, command_line) "
            "VALUES (?, 'test', 'network', 'outbound', 'high', '2026-07-18 10:00:01', "
            "'8.8.8.8', 'powershell.exe', 'IWR http://8.8.8.8/x')", (host_id,))
        conn.execute(
            "INSERT INTO rules "
            "(name, description, category, rule_type, condition, severity, enabled) "
            "VALUES ('Suspicious Beacon', 'beacon detect', 'malware', 'detection', "
            "'{}', 'high', 1)")
        return host_id


class TestTriggerNodeTriage(unittest.TestCase):
    """node_type='trigger' 的单节点调试行为测试。"""

    @classmethod
    def setUpClass(cls):
        """建立临时测试库并初始化表结构。"""
        db_path = Path(TEST_DB_PATH)
        if db_path.exists():
            try:
                db_path.unlink()
            except OSError:
                pass
        from app.config import settings
        settings.DB_PATH = TEST_DB_PATH
        Path(settings.DATA_DIR).mkdir(parents=True, exist_ok=True)
        from app.database import init_db
        init_db()

    def setUp(self):
        """每个用例使用独立引擎实例，并重置库确保数据干净。"""
        from app.services.agents.pipeline_engine import PipelineEngine
        self.engine = PipelineEngine()

    def _run(self, **kwargs):
        """同步包装异步 execute_node。"""
        return asyncio.run(self.engine.execute_node(**kwargs))

    # ── simulate 模式 ──
    def test_simulate_trigger_returns_triage_fixture(self):
        """simulate 模式应返回 SIMULATE_TRIAGE，含 P0/P1、confidence>0、stage='triage'。"""
        res = self._run(
            node_type="trigger",
            node_name="触发器",
            input_params={},
            context_vars={"event_id": "SE-1"},
            mode="simulate",
            user={},
        )
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["node_type"], "trigger")
        # output 含优先级标记（P0 / P1）
        self.assertTrue(
            ("P0" in res["output_text"]) or ("P1" in res["output_text"]),
            msg=f"output 应含 P0/P1，实际：{res['output_text'][:120]}",
        )
        self.assertGreater(res["confidence"], 0)
        self.assertEqual(res["result"]["structured"]["stage"], "triage")
        # fixture 的 structured 额外字段
        self.assertIn("priority", res["result"]["structured"])
        self.assertIn("event_id", res["result"]["structured"])

    # ── real 模式 ──
    def test_real_trigger_runs_triage_agent(self):
        """real 模式应调用 TriageAgent 对 SE-1 做真实分诊（成功、output 非空、confidence>0）。"""
        seed_full_incident()
        res = self._run(
            node_type="trigger",
            node_name="触发器",
            input_params={},
            context_vars={"event_id": "SE-1"},
            mode="real",
            user={},
        )
        self.assertEqual(res["status"], "success", msg=res.get("error"))
        self.assertTrue(res["output_text"], msg="real 模式分诊 output 不应为空")
        self.assertGreater(res["confidence"], 0, msg="分诊置信度应 > 0")
        self.assertEqual(res["result"]["structured"]["stage"], "triage")
        # 不依赖 LLM 内容：仅断言结构化字段存在且合理
        self.assertEqual(res["result"]["structured"]["event_id"], "SE-1")

    # ── 缺失 event_id 失败路径 ──
    def test_missing_event_id_fails_with_hint(self):
        """缺失 event_id 时应 status=failed 且 output 含友好提示，不抛异常（不返回 500）。"""
        res = self._run(
            node_type="trigger",
            node_name="触发器",
            input_params={},
            context_vars={},
            mode="real",
            user={},
        )
        self.assertEqual(res["status"], "failed")
        self.assertIn("请提供 event_id", res["output_text"])
        self.assertIsNotNone(res["run_id"])  # 失败仍落库，便于回溯

    def test_missing_event_id_simulate_still_success(self):
        """simulate 模式不依赖 event_id，缺失时仍成功返回 fixture。"""
        res = self._run(
            node_type="trigger",
            node_name="触发器",
            input_params={},
            context_vars={},
            mode="simulate",
            user={},
        )
        self.assertEqual(res["status"], "success")
        self.assertGreater(res["confidence"], 0)


if __name__ == "__main__":
    unittest.main()
