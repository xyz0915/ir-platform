"""T05-1 / T05-2：guard 护栏映射修复（P0）+ hitl 人工审核节点（P1）单元测试。

设计依据：``node-impl/design.md`` A3.1/A3.2 + B4 验收标准；``node-impl/dev.md`` §2.1/§2.2。

覆盖：
- guard：``_get_node_runner('guard')`` 命中 ``_run_guardrail``（映射 bug 修复验证）；
  ``'guardrail'`` 键向后兼容；block=true → status=blocked；block=false → success；
  ``execute_node('guard', ...)`` 包装层状态映射（B4 验收）；
  preset agent 注册（name='guard'、hitl=False）。
- hitl：``_run_hitl`` 返回 hitl_triggered=True + action/target；默认参数兜底；
  ``_execute_agent`` 透传 hitl_triggered（不再硬编码 False）；
  preset hitl agent hitl=True 且 config 顶层携带 action/target（供 _create_hitl_approval 读取）。

**零 DB 策略**：execute_node 路径通过 monkeypatch ``NodeRunRepository.persist_debug_run``
规避历史落库（与 test_p0_custom_agent_real_execution 一致，毫秒级执行）。
"""
import asyncio
import sys
import types
import uuid
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.models.agent_run import NodeRunRepository  # noqa: E402
from app.services.agents.agent_definition import AgentDefinition  # noqa: E402
from app.services.agents.pipeline_engine import PipelineEngine  # noqa: E402


@pytest.fixture(autouse=True)
def _noop_node_history(monkeypatch):
    """execute_node 的历史落库改为 no-op，避免触 DB。"""
    monkeypatch.setattr(NodeRunRepository, "persist_debug_run", staticmethod(lambda **kw: "noop-run"))


def _run(coro):
    """同步包装协程。"""
    return asyncio.run(coro)


def _ctx(**kw) -> dict:
    """构造 runner 执行上下文。"""
    return {
        "host_id": kw.get("host_id", "H1"),
        "event_id": kw.get("event_id"),
        "stages": kw.get("stages", []),
        "input_params": kw.get("input_params", {}),
        "context_vars": kw.get("context_vars", {}),
    }


class TestGuardMapping:
    """T05-1 guard 映射 bug 修复验证。"""

    def test_guard_runner_hits_run_guardrail(self):
        """_get_node_runner('guard') 必须命中 _run_guardrail（P0 修复核心）。"""
        eng = PipelineEngine()
        assert eng._get_node_runner("guard") == eng._run_guardrail

    def test_guardrail_key_backward_compat(self):
        """'guardrail' 键仍可用（向后兼容）。"""
        eng = PipelineEngine()
        assert eng._get_node_runner("guardrail") == eng._run_guardrail

    def test_block_true_returns_blocked(self):
        """block=true → status='blocked' + structured.blocked=True（阻断下游语义）。"""
        eng = PipelineEngine()
        r = _run(eng._run_guardrail(_ctx(), {"block": True, "reason": "违规外联", "policy": "strict"}, "real"))
        assert r["status"] == "blocked"
        assert r["structured"]["blocked"] is True
        assert r["confidence"] == 0.0

    def test_block_false_returns_success(self):
        """block=false → status='success' + structured.blocked=False（默认放行）。"""
        eng = PipelineEngine()
        r = _run(eng._run_guardrail(_ctx(), {"block": False, "policy": "default"}, "real"))
        assert r["status"] == "success"
        assert r["structured"]["blocked"] is False
        assert r["confidence"] == 1.0

    def test_execute_node_guard_blocked_maps_blocked(self):
        """B4 验收：execute_node('guard', {block:true}) → 顶层 status='blocked'。

        当前实现 execute_node 仅把 runner 的 status=='failed' 映射为 failed，
        'blocked' 未被映射 → 顶层返回 'success'（structured.blocked=True）。
        按验收标准断言 status == 'blocked'。
        """
        eng = PipelineEngine()
        r = _run(eng.execute_node("guard", "guard", {"block": True, "reason": "x"}, {"host_id": "H1"}, "real", {}))
        assert r["status"] == "blocked", f"B4 期望 status='blocked'，实际 {r['status']!r}（structured.blocked={r['result']['structured'].get('blocked')}）"

    def test_execute_node_guard_pass_success(self):
        """execute_node('guard', {block:false}) → status='success'。"""
        eng = PipelineEngine()
        r = _run(eng.execute_node("guard", "guard", {"block": False}, {"host_id": "H1"}, "real", {}))
        assert r["status"] == "success"
        assert r["result"]["structured"]["blocked"] is False

    def test_guard_preset_agent_registered(self):
        """preset_data 注册 guard agent（name='guard'、hitl=False）。"""
        from app.services.agents.preset_data import PRESET_AGENTS
        guard = next((a for a in PRESET_AGENTS if a["name"] == "guard"), None)
        assert guard is not None
        assert guard["hitl"] is False
        assert guard["config"]["input_params"]["block"] is False


class TestHitlNode:
    """T05-2 hitl 人工审核节点。"""

    def test_run_hitl_returns_triggered_with_action_target(self):
        """_run_hitl 返回 hitl_triggered=True + structured.action/target。"""
        eng = PipelineEngine()
        r = _run(eng._run_hitl(_ctx(), {"action": "block_ip", "target": {"ip": "8.8.8.8"}}, "real"))
        assert r["hitl_triggered"] is True
        assert r["structured"]["hitl_triggered"] is True
        assert r["structured"]["action"] == "block_ip"
        assert r["structured"]["target"] == {"ip": "8.8.8.8"}

    def test_run_hitl_default_action(self):
        """无参数 → action 默认 export_report、target 默认 {}。"""
        eng = PipelineEngine()
        r = _run(eng._run_hitl(_ctx(), {}, "real"))
        assert r["structured"]["action"] == "export_report"
        assert r["structured"]["target"] == {}

    def test_execute_agent_passthrough_hitl_flag(self):
        """_execute_agent 对 hitl 节点透传 hitl_triggered（不再硬编码 False）。"""
        eng = PipelineEngine()
        agent_def = AgentDefinition(
            name="hitl",
            display_name="人工审核",
            description="",
            type="custom",
            hitl=True,
            config={"input_params": {"action": "block_ip", "target": {"ip": "1.1.1.1"}}},
        )
        run = types.SimpleNamespace(ctx={"host_id": "H1", "input_params": {}}, event_id=None, stages=[])
        res = _run(eng._execute_agent(agent_def, run))
        assert res["hitl_triggered"] is True
        assert res["structured"]["action"] == "block_ip"

    def test_execute_agent_non_hitl_no_flag(self):
        """非 hitl 节点（guard）经 _execute_agent 返回 hitl_triggered=False。"""
        eng = PipelineEngine()
        agent_def = AgentDefinition(
            name="guard",
            display_name="护栏",
            description="",
            type="custom",
            hitl=False,
            config={"input_params": {"block": False}},
        )
        run = types.SimpleNamespace(ctx={"host_id": "H1", "input_params": {}}, event_id=None, stages=[])
        res = _run(eng._execute_agent(agent_def, run))
        assert res["hitl_triggered"] is False

    def test_hitl_preset_agent_hitl_true_with_config(self):
        """preset hitl agent：hitl=True + config 顶层 action/target（供 _create_hitl_approval）。"""
        from app.services.agents.preset_data import PRESET_AGENTS
        hitl = next((a for a in PRESET_AGENTS if a["name"] == "hitl"), None)
        assert hitl is not None
        assert hitl["hitl"] is True
        assert hitl["config"]["action"] == "export_report"
        assert isinstance(hitl["config"]["target"], dict)
        assert hitl["config"]["input_params"]["action"] == "export_report"
