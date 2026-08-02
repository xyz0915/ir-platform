"""T05-1 P0 单元测试：自定义智能体真实执行（``_run_unknown`` 增强）。

设计依据：``custom-agent/design.md`` §2（P0 行为矩阵）+ 验收标准 §11 P0。

覆盖：
- tools + model_profile → used_llm/used_tools=true, confidence=0.8,
  evidence 含 ``tool_call`` success 条目；
- 仅 model_profile → LLM 生成结论（used_llm=true, used_tools=false）；
- 仅 tools → 工具结果摘要 + evidence（used_tools=true, used_llm=false）；
- 都无 → 原静态摘要兜底（输出形状不变，未联网）；
- 工具失败 / 异常 / 超时 → 不阻断（evidence 记 failed，errors 有提示）；
- LLM 异常 / 降级 → 降级摘要 + structured.errors；
- ``_call_llm_safe`` 超时路径 → used=false + error 含超时；
- ``_resolve_llm_profile`` 解析：id → profile_name → 激活兜底；
- ``ToolRegistry.call_tool`` 三态：未注册 / 服务器缺失 / 正常调用 / transport 异常。

**测试速度优化**：本文件不依赖 conftest 的 ``db_path``/``engine`` fixture
（每个用例 init_db+seed 约 12s）。``_run_unknown`` 的所有外部依赖
（AiConfigProfile / AgentLLM / ToolRegistry / McpTool）均被 mock/stub，
因此直接构造 ``PipelineEngine()`` 即可，全程零 DB 访问，毫秒级执行。
"""

import asyncio
import uuid

import pytest

from app.models.ai_config import AiConfigProfile
from app.services import agent_llm as agent_llm_module
from app.services.agents.agent_definition import AgentDefinition
from app.services.agents.pipeline_engine import PipelineEngine
from app.services.mcp.registry import ToolRegistry

# 显式导入共享 fixture（pytest 解析）
from helpers.agent_test_utils import fake_profiles, mock_profiles, mock_llm_ok, mock_tools  # noqa: F401


@pytest.fixture(autouse=True)
def _stub_mcp_tool_lookup(monkeypatch):
    """让 ``_tool_timeout`` 不触碰任何 DB：``McpTool.get_by_id`` 恒返回 None。

    ToolRegistry.call_tool 三态用例会在测试体内自行覆盖该 stub。
    """
    from app.models.mcp import McpTool
    monkeypatch.setattr(McpTool, "get_by_id", staticmethod(lambda tool_id: None))


def _ctx(**kw) -> dict:
    """构造 _run_unknown 执行上下文（与 _execute_agent 同构）。"""
    return {
        "host_id": kw.get("host_id"),
        "event_id": kw.get("event_id", "SE-1"),
        "input_params": kw.get("input_params", {}),
        "context_vars": kw.get("context_vars", {"user": {"id": 1}}),
    }


def _def(**kw) -> AgentDefinition:
    """构造唯一命名的自定义 Agent 定义。"""
    return AgentDefinition(
        name=kw.get("name") or f"qa_custom_{uuid.uuid4().hex[:6]}",
        display_name=kw.get("display_name", "自定义智能体"),
        description=kw.get("description", "测试职责描述"),
        data_sources=kw.get("data_sources", []),
        depends_on=kw.get("depends_on", []),
        tools=kw.get("tools", []),
        model_profile=kw.get("model_profile", ""),
    )


def _run(coro):
    """同步包装协程（等价 conftest run_async，避免引入 db_path）。"""
    import asyncio as _asyncio
    return _asyncio.run(coro)


class TestP0RunUnknown:
    """_run_unknown 行为矩阵。"""

    def test_tools_and_model_profile_real_execution(
        self, mock_profiles, mock_llm_ok, mock_tools
    ):
        """tools + model_profile → 真实调工具 + 真实调 LLM。"""
        engine = PipelineEngine()
        agent_def = _def(tools=["tool-a"], model_profile="1")
        res = _run(engine._run_unknown(agent_def, _ctx()))

        assert res["structured"]["used_llm"] is True
        assert res["structured"]["used_tools"] is True
        assert res["confidence"] == 0.8
        # output 为 LLM 结论（mock 内容）
        assert res["output"].startswith("__LLM_CONTENT__")
        # evidence 含 tool_call success
        assert any(
            e["type"] == "tool_call" and e["status"] == "success" and e["ref"] == "tool-a"
            for e in res["evidence"]
        )
        assert res["structured"]["model_profile"] == "1"
        assert res["structured"]["tools"] == ["tool-a"]
        # LLM 恰好调用一次
        assert len(mock_llm_ok) == 1

    def test_only_model_profile_uses_llm(self, mock_profiles, mock_llm_ok, mock_tools):
        """仅 model_profile → LLM 生成结论（自动构造 prompt）。"""
        engine = PipelineEngine()
        agent_def = _def(model_profile="1", description="分析职责A")
        res = _run(engine._run_unknown(agent_def, _ctx()))

        assert res["structured"]["used_llm"] is True
        assert res["structured"]["used_tools"] is False
        assert res["confidence"] == 0.8
        assert res["output"].startswith("__LLM_CONTENT__")
        # 自动构造的 prompt 含分析师职责与智能体描述
        prompt = mock_llm_ok[0]["prompt"]
        assert "应急响应分析师" in prompt
        assert "分析职责A" in prompt
        assert res["structured"]["errors"] == []

    def test_only_tools_summarizes_tool_results(self, mock_profiles, mock_llm_ok, mock_tools):
        """仅 tools → 工具结果摘要 + evidence；不调 LLM。"""
        engine = PipelineEngine()
        agent_def = _def(tools=["tool-a", "tool-b"])
        res = _run(engine._run_unknown(agent_def, _ctx()))

        assert res["structured"]["used_llm"] is False
        assert res["structured"]["used_tools"] is True
        assert len(mock_llm_ok) == 0  # 未联网
        # 兜底摘要含工具执行统计
        assert "工具执行: 2 个工具已调用" in res["output"]
        assert len(res["evidence"]) == 2
        assert all(e["type"] == "tool_call" and e["status"] == "success" for e in res["evidence"])

    def test_no_config_falls_back_to_static_summary(self, mock_profiles, mock_llm_ok, mock_tools):
        """都无 → 原静态摘要兜底（输出形状与旧实现一致，无联网）。"""
        engine = PipelineEngine()
        agent_def = _def(display_name="静态兜底", depends_on=["triage"], data_sources=["security_events"])
        res = _run(engine._run_unknown(agent_def, _ctx()))

        assert res["structured"]["used_llm"] is False
        assert res["structured"]["used_tools"] is False
        assert res["confidence"] == 0.5
        assert len(mock_llm_ok) == 0
        out = res["output"]
        assert out.startswith("# 静态兜底")
        assert "数据源: security_events" in out
        assert "依赖: triage" in out
        assert res["evidence"] == []
        assert res["structured"]["errors"] == []

    # ── 失败不阻断 ──

    def test_tool_failure_does_not_block(self, mock_profiles, mock_llm_ok, mock_tools):
        """工具返回 ok=False → evidence 记 failed，不抛异常。"""
        def handler(tool_id, args):
            return {"ok": False, "tool_id": tool_id, "error": "server offline"}

        mock_tools["handler"] = handler
        engine = PipelineEngine()
        agent_def = _def(tools=["tool-bad"])
        res = _run(engine._run_unknown(agent_def, _ctx()))

        assert res["structured"]["used_tools"] is False
        failed = [e for e in res["evidence"] if e.get("status") == "failed"]
        assert failed and failed[0]["ref"] == "tool-bad"
        assert failed[0]["error"] == "server offline"
        assert any("tool-bad" in e for e in res["structured"]["errors"])
        # 兜底摘要仍输出，且带执行提示
        assert res["output"]
        assert "执行提示" in res["output"]

    def test_tool_exception_does_not_block(self, mock_profiles, mock_llm_ok, mock_tools):
        """工具抛异常 → evidence 记 failed(error=异常信息)，不抛异常。"""
        def handler(tool_id, args):
            raise RuntimeError("boom")

        mock_tools["handler"] = handler
        engine = PipelineEngine()
        agent_def = _def(tools=["tool-boom"])
        res = _run(engine._run_unknown(agent_def, _ctx()))

        assert res["structured"]["used_tools"] is False
        failed = [e for e in res["evidence"] if e.get("status") == "failed"]
        assert failed and failed[0]["error"] == "boom"
        assert any("boom" in e for e in res["structured"]["errors"])

    def test_tool_timeout_does_not_block(self, mock_profiles, mock_llm_ok, mock_tools):
        """工具超时 → evidence 记 failed(error=timeout)，不抛异常。

        说明：真实 ``asyncio.wait_for`` 超时需线程 + 秒级等待，且与 Windows
        sqlite/thread 环境存在进程级崩溃风险（见 test.md 已知环境问题）。
        本用例通过让工具调用抛出 ``asyncio.TimeoutError`` 精确覆盖
        ``_run_tools_safe`` 的 ``except asyncio.TimeoutError`` 分支（确定性、零等待）。
        """
        def handler(tool_id, args):
            raise asyncio.TimeoutError()

        mock_tools["handler"] = handler
        engine = PipelineEngine()
        agent_def = _def(tools=["tool-slow"])
        res = _run(engine._run_unknown(agent_def, _ctx()))

        assert res["structured"]["used_tools"] is False
        failed = [e for e in res["evidence"] if e.get("status") == "failed"]
        assert failed and failed[0]["error"] == "timeout"
        assert any("tool-slow" in e for e in res["structured"]["errors"])

    # ── LLM 降级/异常 ──

    def test_llm_exception_falls_back(self, mock_profiles, mock_tools, monkeypatch):
        """LLM 抛异常 → used_llm=false + structured.errors，降级摘要。"""
        class BoomLLM:
            def __init__(self, profile=None):
                self.profile = profile

            async def call(self, prompt, user=None, trace_id=None, **kwargs):
                raise RuntimeError("llm boom")

        monkeypatch.setattr(agent_llm_module, "AgentLLM", BoomLLM)
        engine = PipelineEngine()
        agent_def = _def(model_profile="1")
        res = _run(engine._run_unknown(agent_def, _ctx()))

        assert res["structured"]["used_llm"] is False
        assert res["confidence"] == 0.5
        assert any("LLM 调用异常" in e for e in res["structured"]["errors"])
        assert res["output"].startswith("# ")

    def test_llm_degraded_falls_back(self, mock_profiles, mock_tools, monkeypatch):
        """LLM 降级（degraded=True）→ used_llm=false + errors 提示（取 resp.error）。"""
        class DegradedLLM:
            def __init__(self, profile=None):
                self.profile = profile

            async def call(self, prompt, user=None, trace_id=None, **kwargs):
                return {"content": "", "degraded": True, "error": "model degraded"}

        monkeypatch.setattr(agent_llm_module, "AgentLLM", DegradedLLM)
        engine = PipelineEngine()
        agent_def = _def(model_profile="1")
        res = _run(engine._run_unknown(agent_def, _ctx()))

        assert res["structured"]["used_llm"] is False
        assert any("model degraded" in e for e in res["structured"]["errors"])
        assert res["output"].startswith("# ")

    def test_call_llm_safe_timeout(self, mock_profiles, monkeypatch):
        """_call_llm_safe 超时路径 → used=false + error 含超时。"""
        class SlowLLM:
            def __init__(self, profile=None):
                self.profile = profile

            async def call(self, prompt, user=None, trace_id=None, **kwargs):
                await asyncio.sleep(1.0)
                return {"content": "x", "degraded": False}

        monkeypatch.setattr(agent_llm_module, "AgentLLM", SlowLLM)
        engine = PipelineEngine()
        res = _run(engine._call_llm_safe({"model_name": "gpt"}, "p", {}, timeout=0.05))
        assert res["used"] is False
        assert "超时" in res["error"]


class TestResolveLlmProfile:
    """_resolve_llm_profile：id → profile_name → 激活兜底。"""

    def test_resolve_by_id(self, mock_profiles):
        p = PipelineEngine()._resolve_llm_profile("1")
        assert p["id"] == 1

    def test_resolve_by_name(self, monkeypatch, fake_profiles):
        monkeypatch.setattr(AiConfigProfile, "get_by_id", staticmethod(lambda pid: None))
        monkeypatch.setattr(AiConfigProfile, "list_all", staticmethod(lambda: list(fake_profiles.values())))
        monkeypatch.setattr(AiConfigProfile, "get_active", staticmethod(lambda: fake_profiles.get(1)))
        p = PipelineEngine()._resolve_llm_profile("备用配置")
        assert p["id"] == 2

    def test_resolve_empty_returns_active(self, mock_profiles):
        p = PipelineEngine()._resolve_llm_profile("")
        assert p["id"] == 1


class TestToolRegistryCallTool:
    """ToolRegistry.call_tool 三态 + transport 异常（design §11 P0 验收）。

    依赖 autouse ``_stub_mcp_tool_lookup``：未注册分支由 stub 返回 None 覆盖
    （等价真实 DB 中查无此工具），无需初始化 DB。
    """

    def test_unregistered_tool(self):
        res = ToolRegistry.call_tool("no-such-tool", {})
        assert res["ok"] is False
        assert "未注册" in res["error"]

    def test_missing_server(self, monkeypatch):
        from app.models.mcp import McpTool
        monkeypatch.setattr(
            McpTool, "get_by_id",
            staticmethod(lambda tid: {"tool_id": tid, "server_id": "srv-x", "name": "tool"}),
        )
        res = ToolRegistry.call_tool("tool-x", {})
        assert res["ok"] is False
        assert "MCP 服务器不存在" in res["error"]

    def test_normal_call(self, monkeypatch):
        from app.models.mcp import McpServer, McpTool
        import app.services.mcp.registry as reg_module

        monkeypatch.setattr(
            McpTool, "get_by_id",
            staticmethod(lambda tid: {"tool_id": tid, "server_id": "srv-1", "name": "real-tool"}),
        )
        monkeypatch.setattr(McpServer, "get_by_id", staticmethod(lambda sid: {"server_id": sid}))

        class FakeTransport:
            def __init__(self):
                self.connected = False

            def connect(self):
                self.connected = True

            def call_tool(self, name, args):
                return {"data": "ok"}

            def disconnect(self):
                self.connected = False

        monkeypatch.setattr(reg_module, "get_transport", staticmethod(lambda server: FakeTransport()))
        res = ToolRegistry.call_tool("tool-x", {"a": 1})
        assert res["ok"] is True
        assert res["result"] == {"data": "ok"}

    def test_transport_error(self, monkeypatch):
        from app.models.mcp import McpServer, McpTool
        import app.services.mcp.registry as reg_module

        monkeypatch.setattr(
            McpTool, "get_by_id",
            staticmethod(lambda tid: {"tool_id": tid, "server_id": "srv-1", "name": "real-tool"}),
        )
        monkeypatch.setattr(McpServer, "get_by_id", staticmethod(lambda sid: {"server_id": sid}))

        class BadTransport:
            def connect(self):
                raise ConnectionError("conn refused")

            def disconnect(self):
                pass

        monkeypatch.setattr(reg_module, "get_transport", staticmethod(lambda server: BadTransport()))
        res = ToolRegistry.call_tool("tool-x", {})
        assert res["ok"] is False
        assert "conn refused" in res["error"]
