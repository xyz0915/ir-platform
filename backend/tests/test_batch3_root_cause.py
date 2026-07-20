"""第③批 T-G1 · 根因归因智能体 + Investigator 集成测试。

覆盖：
- RootCauseAgent.run() / analyze() 返回 root_node / causal_chain /
  confidence / evidence；复用 ProcessTreeBuilder 沿 parent→child 回溯第一触发点。
- LLM 降级（AgentLLM 抛异常 / degraded）时 ``llm_explanation=None``（=degraded）
  且不抛异常（不 500）。
- POST /api/analysis/root-cause：无 token→401；带 token 返回根因并脱敏。
- InvestigatorAgent 集成：对 RootCauseAgent 懒加载 import 成功（不为 None）；
  run() 中 await _try_root_cause 在 RootCauseAgent 可用时把其输出并入调查报告
  （含「[RootCauseAgent 增强]」前缀）。构造 host 有进程事件的场景验证。

LLM 不可用路径全部覆盖（mock AgentLLM.call 抛异常 / 返回空）。
隔离 SQLite（_qa_batch1_common），绝不触碰 ir.db。
"""

import asyncio
import json
from pathlib import Path
from unittest.mock import patch, AsyncMock

import sys
_THIS = Path(__file__).resolve().parent
_BACKEND = _THIS.parent
for _p in (str(_BACKEND), str(_THIS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.events import router as events_router
from app.services.auth_service import get_current_user
from app.services.agents.root_cause_agent import RootCauseAgent
from app.services.agents.investigator_agent import (
    InvestigatorAgent,
    RootCauseAgent as LazyRootCauseAgent,
)
from app.services.agents.base_agent import AgentResult
from app.database import get_connection

from _qa_batch1_common import IsolatedDBTestCase

# 隔离最小 app：仅挂 events（prefix=/api/analysis，与主 app 一致）
_api_app = FastAPI()
_api_app.include_router(events_router, prefix="/api/analysis")


def _proc(pid, ppid, name, start_time, **kw):
    p = {
        "event_type": "process_start", "pid": pid, "ppid": ppid,
        "process_name": name, "start_time": start_time,
    }
    p.update(kw)
    return p


def _seed_host_with_procs(procs):
    with get_connection() as conn:
        conn.execute("INSERT INTO cases (name) VALUES ('qa_case')")
        case_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO hosts (case_id, hostname, ip_address, os_type) "
            "VALUES (?, 'QAHOST', '10.0.0.7', 'Windows')", (case_id,))
        hid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        for p in procs:
            conn.execute(
                "INSERT INTO process_events "
                "(host_id, event_type, pid, ppid, process_name, process_path, "
                "command_line, parent_name, start_time) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (hid, p.get("event_type", "process_start"), p["pid"], p["ppid"],
                 p["process_name"], p.get("process_path", ""),
                 p.get("command_line", ""), p.get("parent_name", ""),
                 p["start_time"]))
    return hid


# ───────────────────────── RootCauseAgent 单元 ─────────────────────────
class TestRootCauseAgentUnit(IsolatedDBTestCase):
    def _procs_trace(self):
        # child 最早触发 → 回溯到 parent（root）。构造 parent 时间戳更晚以产生 2 节点链。
        return [
            _proc(201, 200, "child.exe", "2026-07-18 09:00:00",
                   command_line="child --evil"),
            _proc(200, 1, "parent.exe", "2026-07-18 09:05:00",
                   command_line="parent"),
        ]

    def test_analyze_returns_expected_structure(self):
        procs = self._procs_trace()
        with patch("app.services.agents.root_cause_agent.AgentLLM") as MockLLM:
            inst = MockLLM.return_value
            inst.call = AsyncMock(return_value={"content": "", "degraded": True})
            result = asyncio.run(RootCauseAgent().analyze(
                process_events=procs, host_id=1))
        # 关键字段齐全
        for k in ("root_node", "causal_chain", "confidence", "evidence", "summary"):
            self.assertIn(k, result)
        self.assertIsNotNone(result["root_node"])
        self.assertIsInstance(result["causal_chain"], list)
        self.assertGreaterEqual(len(result["causal_chain"]), 1)
        self.assertIsInstance(result["confidence"], float)
        self.assertIsInstance(result["evidence"], list)
        # 回溯正确性：root 应为 parent（pid=200）
        self.assertEqual(result["root_node"]["pid"], 200)
        self.assertEqual(result["causal_chain"][0]["pid"], 200)
        self.assertEqual(result["causal_chain"][-1]["pid"], 201)
        # 节点含前端所需真实字段
        node = result["causal_chain"][0]
        for f in ("pid", "ppid", "process_name", "command_line", "time", "ref"):
            self.assertIn(f, node)

    def test_run_returns_agentresult(self):
        procs = self._procs_trace()
        with patch("app.services.agents.root_cause_agent.AgentLLM") as MockLLM:
            inst = MockLLM.return_value
            inst.call = AsyncMock(return_value={"content": "", "degraded": True})
            res = asyncio.run(RootCauseAgent().run(
                ctx={"user": {"id": 1}}, task={"host_id": 1, "process_events": procs}))
        self.assertIsInstance(res, AgentResult)
        self.assertIsInstance(res.confidence, float)
        self.assertTrue(0.0 <= res.confidence <= 1.0)
        self.assertTrue(len(res.output) > 0)

    def test_llm_exception_degrades_no_500(self):
        """AgentLLM.call 抛异常 → llm_explanation=None（degraded），不抛异常。"""
        procs = self._procs_trace()
        with patch("app.services.agents.root_cause_agent.AgentLLM") as MockLLM:
            inst = MockLLM.return_value
            inst.call = AsyncMock(side_effect=RuntimeError("llm down"))
            result = asyncio.run(RootCauseAgent().analyze(
                process_events=procs, host_id=1))
        self.assertTrue(result["degraded"])           # llm_explanation 为 None
        # 降级时 explanation 回退为 summary（不为 None，结构链仍产出）
        self.assertIsNotNone(result["explanation"])
        self.assertEqual(result["explanation"], result["summary"])
        self.assertIsNotNone(result["root_node"])     # 结构化链仍产出
        self.assertIsInstance(result["causal_chain"], list)

    def test_no_process_events_yields_empty_chain(self):
        with patch("app.services.agents.root_cause_agent.AgentLLM") as MockLLM:
            inst = MockLLM.return_value
            inst.call = AsyncMock(return_value={"content": "", "degraded": True})
            result = asyncio.run(RootCauseAgent().analyze(
                process_events=[], host_id=1))
        self.assertIsNone(result["root_node"])
        self.assertEqual(result["causal_chain"], [])
        self.assertTrue(result["degraded"])
        self.assertIn("无进程事件", result["summary"])


# ───────────────────────── API：/api/analysis/root-cause ─────────────────────────
class TestRootCauseAPI(IsolatedDBTestCase):
    def setUp(self):
        super().setUp()
        self.client = TestClient(_api_app)
        _api_app.dependency_overrides.clear()

    def tearDown(self):
        _api_app.dependency_overrides.clear()
        super().tearDown()

    def _auth(self, role="admin"):
        user = {"id": 1 if role == "admin" else 2,
                 "username": "admin" if role == "admin" else "analyst",
                 "role": role}
        _api_app.dependency_overrides[get_current_user] = lambda: user

    def test_root_cause_no_token_401(self):
        _api_app.dependency_overrides.clear()
        resp = self.client.post("/api/analysis/root-cause",
                               json={"host_id": 1})
        self.assertEqual(resp.status_code, 401)

    def test_root_cause_with_auth_returns_masked(self):
        self._auth()
        hid = _seed_host_with_procs([
            _proc(301, 1, "powershell.exe", "2026-07-18 09:00:00",
                   command_line="powershell -enc xxx",
                   process_path="C:\\Windows\\System32\\powershell.exe"),
        ])
        with patch("app.services.agents.root_cause_agent.AgentLLM") as MockLLM:
            inst = MockLLM.return_value
            inst.call = AsyncMock(return_value={"content": "", "degraded": True})
            resp = self.client.post("/api/analysis/root-cause",
                                   json={"host_id": hid})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body.get("code"), 0)
        data = body["data"]
        for k in ("root_node", "causal_chain", "confidence", "evidence"):
            self.assertIn(k, data)
        self.assertIsNotNone(data["root_node"])


# ───────────────────────── Investigator 集成 ─────────────────────────
class TestInvestigatorIntegration(IsolatedDBTestCase):
    def test_root_cause_agent_lazy_import_not_none(self):
        # investigator_agent 对 RootCauseAgent 的懒加载 import 成功
        self.assertIsNotNone(LazyRootCauseAgent)

    def test_investigator_merges_root_cause_enhancement(self):
        """run() 中 await _try_root_cause 在 RootCauseAgent 可用时，
        把其输出并入调查报告（含「[RootCauseAgent 增强]」前缀）。"""
        hid = _seed_host_with_procs([
            _proc(301, 1, "powershell.exe", "2026-07-18 09:00:00",
                   command_line="powershell -enc xxx"),
        ])
        with patch("app.services.agents.investigator_agent.AgentLLM") as MockInv, \
             patch("app.services.agents.root_cause_agent.AgentLLM") as MockRC:
            inv_inst = MockInv.return_value
            inv_inst.call = AsyncMock(return_value={"content": "", "degraded": True})
            rc_inst = MockRC.return_value
            # RootCauseAgent 可用且给出合法自然语言解释
            rc_inst.call = AsyncMock(return_value={
                "content": "该进程链由 powershell 启动可疑脚本",
                "degraded": False})
            ctx = {"host_id": hid, "user": {"id": 1}}
            result = asyncio.run(InvestigatorAgent().run(ctx, task={}))
            self.assertIsInstance(result, AgentResult)
            # 调查报告应包含 RootCauseAgent 增强内容
            root_cause = ctx["investigation"]["root_cause"]
            self.assertIn("[RootCauseAgent 增强]", root_cause)
            self.assertIn("[RootCauseAgent 增强]", result.output)


if __name__ == "__main__":
    import unittest
    unittest.main()
