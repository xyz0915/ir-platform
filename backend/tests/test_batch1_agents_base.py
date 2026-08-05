"""第①批 T-F1 共享底座测试：AgentLLM / BaseAgent / Orchestrator / 模型 CRUD.

覆盖：
- AgentLLM.call：未配置 Profile / 熔断 / 异常 → degraded=True 不抛 500；正常路径 mock AiService.call_llm 写 ai_audit_log(user_id)。
- BaseAgent：抽象类不可实例化；子类 run 返回 AgentResult（含 evidence）。
- Orchestrator：start_run 写 agent_runs；dispatch 驱动 Agent 写 agent_run_steps；waiting_hitl 网关。
- AgentRun / AgentRunStep / HitlApproval 模型 CRUD。
"""

import asyncio
from unittest.mock import patch, AsyncMock

import httpx

from app.services.agent_llm import AgentLLM
from app.services.agents.base_agent import BaseAgent, AgentResult
from app.services.agents.orchestrator import Orchestrator
from app.services.ai_service import AiService
from app.models.ai_audit_log import AiAuditLog
from app.models.agent_run import AgentRun, AgentRunStep
from app.models.hitl_approval import HitlApproval

from _qa_batch1_common import IsolatedDBTestCase


# ───────────────────────── AgentLLM ─────────────────────────
class _FakeProfile:
    """构造一个“已配置”的 Profile 字典（api_key 用明文，decrypt 被打桩）。"""

    def __init__(self):
        self.data = {
            "id": 1,
            "profile_name": "qa_profile",
            "api_key": "enc-key",
            "api_base_url": "http://llm.local/v1",
            "model_name": "gpt-4o",
            "max_tokens": 4096,
            "temperature": 0.3,
            "system_prompt": "sys",
        }


class TestAgentLLM(IsolatedDBTestCase):
    def test_no_profile_returns_degraded_no_500(self):
        """未配置 Profile → degraded=True，返回错误文案，不抛异常（安全降级）。"""
        res = asyncio.run(AgentLLM().call("任何 prompt", {"id": 9}))
        self.assertTrue(res["degraded"])
        # 未配置 Profile 时仍给出可读的错误文案（源码 agent_llm.py:58）
        self.assertIsNotNone(res["error"])
        self.assertIn("Profile", res["error"])
        # 未配置 Profile 时不写失败审计（_degraded 仅在 profile 非 None 时落审计）
        self.assertEqual(AiAuditLog.list_all()["total"], 0)

    def test_normal_path_writes_success_audit(self):
        """正常路径：mock AiService.call_llm 返回内容，写 ai_audit_log(status=success, user_id)。"""
        profile = _FakeProfile().data
        fake_llm = {
            "choices": [{"message": {"content": "分析结论文本"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
        with patch.object(AiService, "decrypt_api_key", return_value="sk-plain"), \
                patch("app.services.ai_service.AiService.call_llm",
                      new=AsyncMock(return_value=fake_llm)):
            res = asyncio.run(AgentLLM(profile=profile).call("prompt", {"id": 7}))
        self.assertFalse(res["degraded"])
        self.assertEqual(res["content"], "分析结论文本")
        items = AiAuditLog.list_all(status="success")["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["user_id"], 7)
        self.assertEqual(items[0]["status"], "success")

    def test_circuit_breaker_returns_degraded_and_writes_failed_audit(self):
        """断路器熔断（RuntimeError 含'熔断'）→ degraded=True，写 failed 审计。"""
        profile = _FakeProfile().data
        with patch.object(AiService, "decrypt_api_key", return_value="sk-plain"), \
                patch("app.services.ai_service.AiService.call_llm",
                      new=AsyncMock(side_effect=RuntimeError("断路器已熔断"))):
            res = asyncio.run(AgentLLM(profile=profile).call("p", {"id": 3}))
        self.assertTrue(res["degraded"])
        self.assertIn("熔断", res["error"])
        failed = AiAuditLog.list_all(status="failed")["items"]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["user_id"], 3)
        self.assertEqual(failed[0]["status"], "failed")

    def test_exception_returns_degraded_and_writes_failed_audit(self):
        """连接异常（httpx.ConnectError）→ degraded=True，写 failed 审计，不抛 500。"""
        profile = _FakeProfile().data
        with patch.object(AiService, "decrypt_api_key", return_value="sk-plain"), \
                patch("app.services.ai_service.AiService.call_llm",
                      new=AsyncMock(side_effect=httpx.ConnectError("connection refused"))):
            res = asyncio.run(AgentLLM(profile=profile).call("p", {"id": 4}))
        self.assertTrue(res["degraded"])
        self.assertIn("连接", res["error"])
        failed = AiAuditLog.list_all(status="failed")["items"]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["user_id"], 4)

    def test_budget_truncation_does_not_crash(self):
        """超长 prompt 触发预算截断，不抛异常。"""
        profile = _FakeProfile().data
        with patch.object(AiService, "decrypt_api_key", return_value="sk-plain"), \
                patch("app.services.ai_service.AiService.call_llm",
                      new=AsyncMock(return_value={"choices": [{"message": {"content": "ok"}}], "usage": {}})):
            res = asyncio.run(AgentLLM(profile=profile).call("x" * 200000, {"id": 1}))
        self.assertFalse(res["degraded"])


# ───────────────────────── BaseAgent / AgentResult ─────────────────────────
class _DummyAgent(BaseAgent):
    name = "dummy_agent"
    role = "test"
    requires_hitl = False

    async def run(self, ctx, task):
        return AgentResult(
            stage="triage",
            output="执行完成",
            confidence=0.85,
            evidence=[{"type": "log", "ref": "normalized_logs:1"}],
            hitl=False,
        )


class _HitlAgent(BaseAgent):
    name = "blocker_agent"
    role = "responder"
    requires_hitl = True

    async def run(self, ctx, task):
        return AgentResult(stage="response", output="建议封禁", confidence=0.9, hitl=True)


class _FailingAgent(BaseAgent):
    name = "failing_agent"
    role = "test"
    requires_hitl = False

    async def run(self, ctx, task):
        raise RuntimeError("boom")


class TestBaseAgent(IsolatedDBTestCase):
    def test_cannot_instantiate_abstract(self):
        """BaseAgent 含抽象方法 run，不能直接实例化。"""
        with self.assertRaises(TypeError):
            BaseAgent()

    def test_concrete_agent_run_returns_agent_result_with_evidence(self):
        """子类 run 返回 AgentResult 且含 evidence。"""
        result = asyncio.run(_DummyAgent().run({}, {}))
        self.assertIsInstance(result, AgentResult)
        self.assertEqual(result.stage, "triage")
        self.assertEqual(result.confidence, 0.85)
        self.assertEqual(result.evidence[0]["ref"], "normalized_logs:1")

    def test_agent_result_to_from_dict_roundtrip(self):
        """AgentResult 序列化/反序列化保持字段一致。"""
        r = AgentResult(stage="investigation", output="o", confidence=0.5,
                         evidence=[{"type": "x", "ref": "y"}], hitl=True)
        d = r.to_dict()
        r2 = AgentResult.from_dict(d)
        self.assertEqual(r2.stage, "investigation")
        self.assertEqual(r2.confidence, 0.5)
        self.assertTrue(r2.hitl)
        self.assertEqual(r2.evidence[0]["ref"], "y")


# ───────────────────────── Orchestrator ─────────────────────────
class TestOrchestrator(IsolatedDBTestCase):
    def test_start_run_writes_agent_runs_row(self):
        """start_run 在临时库写入一条 agent_runs（pending）。"""
        run = Orchestrator().start_run(event_id="evt-1", title="T", user={"id": 2})
        self.assertEqual(run["status"], "pending")
        fetched = AgentRun.get_by_run_id(run["run_id"])
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["user_id"], 2)

    def test_dispatch_drives_agent_and_writes_step(self):
        """dispatch 串行执行 Agent 并写 agent_run_steps。

        语义（A3）：dispatch() 默认 is_final=False，仅置 run=running
        （orchestrator.py:104）；completed 由 _finish_with_reporter(is_final=True)
        收尾。故此处断言 running，与同文件 HITL/fail 用例对称。
        """
        orch = Orchestrator()
        run = orch.start_run(title="dispatch")
        rid = run["run_id"]
        result = asyncio.run(orch.dispatch(rid, _DummyAgent(), ctx={}, task={}))
        self.assertEqual(result.confidence, 0.85)
        steps = AgentRunStep.list_by_run(rid)
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0]["status"], "success")
        self.assertEqual(steps[0]["agent"], "dummy_agent")
        self.assertEqual(AgentRun.get_by_run_id(rid)["status"], "running")

    def test_dispatch_hitl_agent_triggers_waiting_gateway(self):
        """requires_hitl 且 result.hitl=True → run=waiting_hitl 且写 hitl_approvals(pending)。"""
        orch = Orchestrator()
        run = orch.start_run(title="hitl")
        rid = run["run_id"]
        asyncio.run(orch.dispatch(rid, _HitlAgent(), ctx={}, task={}))
        self.assertEqual(AgentRun.get_by_run_id(rid)["status"], "waiting_hitl")
        approvals = HitlApproval.list_by_run(rid)
        self.assertEqual(len(approvals), 1)
        self.assertEqual(approvals[0]["status"], "pending")

    def test_dispatch_failing_agent_marks_run_failed(self):
        """Agent 抛异常被捕获 → run=Failed（不向上抛 500）。"""
        orch = Orchestrator()
        run = orch.start_run(title="fail")
        rid = run["run_id"]
        result = asyncio.run(orch.dispatch(rid, _FailingAgent(), ctx={}, task={}))
        self.assertEqual(AgentRun.get_by_run_id(rid)["status"], "failed")
        steps = AgentRunStep.list_by_run(rid)
        self.assertEqual(steps[0]["status"], "failed")
        self.assertEqual(result.confidence, 0.0)


# ───────────────────────── 模型 CRUD ─────────────────────────
class TestAgentRunModel(IsolatedDBTestCase):
    def test_crud(self):
        run = AgentRun.create(run_id="run_crud1", title="c", user_id=1)
        self.assertEqual(AgentRun.get_by_id(run["id"])["run_id"], "run_crud1")
        self.assertEqual(AgentRun.get_by_run_id("run_crud1")["status"], "pending")
        updated = AgentRun.update("run_crud1", status="running", confidence=0.7)
        self.assertEqual(updated["status"], "running")
        self.assertEqual(updated["confidence"], 0.7)
        listing = AgentRun.list_all()
        self.assertGreaterEqual(listing["total"], 1)


class TestAgentRunStepModel(IsolatedDBTestCase):
    def test_add_and_list(self):
        AgentRun.create(run_id="run_step1")
        step = AgentRunStep.add(
            run_id="run_step1", stage="triage", agent="a", status="success",
            output_json={"x": 1}, evidence_json=[{"type": "log", "ref": "r"}],
        )
        self.assertEqual(step["agent"], "a")
        steps = AgentRunStep.list_by_run("run_step1")
        self.assertEqual(len(steps), 1)
        self.assertEqual(step["id"], steps[0]["id"])


class TestHitlApprovalModel(IsolatedDBTestCase):
    def test_crud(self):
        AgentRun.create(run_id="run_hitl1")
        ap = HitlApproval.create(run_id="run_hitl1", action="block_ip",
                                 requested_by=1, reason="高危")
        self.assertEqual(ap["status"], "pending")
        self.assertEqual(HitlApproval.get_by_id(ap["id"])["action"], "block_ip")
        # 非法状态应抛 ValueError
        with self.assertRaises(ValueError):
            HitlApproval.update_status(ap["id"], "not_a_status")
        approved = HitlApproval.update_status(ap["id"], "approved", decided_by=2, reason="ok")
        self.assertEqual(approved["status"], "approved")
        self.assertEqual(approved["decided_by"], 2)
        self.assertEqual(len(HitlApproval.list_pending()["items"]), 0)
        self.assertEqual(len(HitlApproval.list_by_run("run_hitl1")), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
