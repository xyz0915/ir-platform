"""T05-2 P1 单元测试：画布 llm 节点 ``agent_ref`` 引用已注册智能体配置。

设计依据：``custom-agent/design.md`` §3.2（合并优先级）+ 验收标准 §11 P1。

覆盖：
- ``agent_ref`` 引用已注册智能体 → 合并其 model_profile/tools，真实调 LLM（mock），
  ``structured.agent_ref`` 回显，prompt 兜底取 description；
- 节点 ``input_params`` 显式 model_profile/tools 覆盖 agent_ref 配置（优先级）；
- ``agent_ref`` 不存在 → 降级静态合成输出，不抛异常；
- 未传 agent_ref/model_profile → 保持静态合成（不联网，向后兼容红线）；
- agent_ref 仅带 tools（无 model_profile）→ 执行工具但不调 LLM。

**测试速度优化**：本文件覆盖 conftest 的 ``db_path`` 为 session 级（整个文件
共享一个临时 SQLite，init_db+seed 只执行一次）。各用例使用唯一 agent 名，
共享库不会互相污染，避免每个用例重复 init_db（约 12s/用例）的开销。
"""

import os
import uuid
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parent.parent
_DATA = _BACKEND / "data"

from app.services.agents.agent_definition import AgentDefinition
from app.services.agents.agent_registry import AgentRegistry

# 显式导入共享 fixture（pytest 解析）
from helpers.agent_test_utils import fake_profiles, mock_profiles, mock_llm_ok, mock_tools  # noqa: F401


@pytest.fixture(scope="session")
def db_path():
    """session 级隔离临时 SQLite：整个文件共享（覆盖 conftest 同名 function fixture）。"""
    from app.config import settings
    original = settings.DB_PATH
    _DATA.mkdir(parents=True, exist_ok=True)
    path = str(_DATA / f"test_p1_agent_ref_{uuid.uuid4().hex[:8]}.db")
    settings.DB_PATH = path
    from app.database import init_db
    init_db()
    from app.services.agents.preset_data import seed_preset_agents
    try:
        seed_preset_agents(AgentRegistry())
    except Exception:
        pass
    yield path
    settings.DB_PATH = original
    for suffix in ("", "-wal", "-shm"):
        try:
            if os.path.exists(path + suffix):
                os.remove(path + suffix)
        except OSError:
            pass


def _ctx(input_params: dict) -> dict:
    """构造 _run_llm 执行上下文（与 execute_node 同构）。"""
    return {
        "host_id": None,
        "event_id": "SE-1",
        "input_params": input_params,
        "context_vars": {"user": {"id": 1}},
    }


def _register(reg: AgentRegistry, name: str, **kw) -> None:
    """幂等注册自定义智能体（避免与预置冲突）。"""
    try:
        reg.register(AgentDefinition(
            name=name,
            display_name=kw.get("display_name", name),
            description=kw.get("description", ""),
            tools=kw.get("tools", []),
            model_profile=kw.get("model_profile", ""),
            config=kw.get("config", {}),
        ))
    except ValueError:
        pass  # 已存在（幂等）


class TestRunLlmAgentRef:
    def test_agent_ref_merges_model_profile_and_tools(
        self, db_path, engine, run_async, mock_profiles, mock_llm_ok, mock_tools
    ):
        """agent_ref 引用已注册智能体 → 合并 model_profile/tools，真实调 LLM。"""
        reg = AgentRegistry()
        _register(reg, "ref-agent", tools=["tool-a"], model_profile="1",
                  description="被引用智能体职责")
        input_params = {"agent_ref": "ref-agent", "query": "分析某事件"}
        res = run_async(engine._run_llm(_ctx(input_params), input_params, "real"))

        assert res["structured"]["agent_ref"] == "ref-agent"
        assert res["structured"]["used_llm"] is True
        assert res["structured"]["model_profile"] == "1"
        assert res["structured"]["tools"] == ["tool-a"]
        assert res["output"].startswith("__LLM_CONTENT__")
        # prompt 兜底取 description
        assert res["structured"]["prompt_used"] == "被引用智能体职责"
        # 工具被真实执行（mock）
        assert any(e["type"] == "tool_call" and e["status"] == "success" for e in res["evidence"])
        assert len(mock_llm_ok) == 1

    def test_node_input_params_override_agent_ref(
        self, db_path, engine, run_async, mock_profiles, mock_llm_ok, mock_tools
    ):
        """节点显式 model_profile/tools 覆盖 agent_ref 配置（优先级）。"""
        reg = AgentRegistry()
        _register(reg, "ref-agent", tools=["tool-a"], model_profile="1")
        input_params = {
            "agent_ref": "ref-agent",
            "query": "q",
            "model_profile": "2",
            "tools": ["tool-b"],
        }
        res = run_async(engine._run_llm(_ctx(input_params), input_params, "real"))

        assert res["structured"]["model_profile"] == "2"
        assert res["structured"]["tools"] == ["tool-b"]
        # LLM 使用节点覆盖后的 profile id=2 调用
        assert res["structured"]["used_llm"] is True
        assert mock_llm_ok[0]["profile"]["id"] == 2
        # 只执行了节点配置的 tool-b（未混入 agent_ref 的 tool-a）
        refs = {e["ref"] for e in res["evidence"] if e["type"] == "tool_call"}
        assert refs == {"tool-b"}

    def test_agent_ref_not_found_falls_back_to_static(
        self, db_path, engine, run_async, mock_profiles, mock_llm_ok, mock_tools
    ):
        """agent_ref 指向不存在智能体 → 降级静态合成，不抛异常。"""
        input_params = {"agent_ref": "ghost-agent", "query": "q"}
        res = run_async(engine._run_llm(_ctx(input_params), input_params, "real"))

        assert res["structured"]["agent_ref"] == "ghost-agent"
        assert res["structured"]["used_llm"] is False
        assert len(mock_llm_ok) == 0
        assert res["output"].startswith("# 自定义大模型节点")
        assert res["structured"]["tools"] == []

    def test_no_agent_ref_no_profile_stays_static(
        self, db_path, engine, run_async, mock_profiles, mock_llm_ok, mock_tools
    ):
        """未传 agent_ref/model_profile → 保持静态合成（不联网，兼容红线）。"""
        input_params = {"query": "q"}
        res = run_async(engine._run_llm(_ctx(input_params), input_params, "real"))

        assert res["structured"]["used_llm"] is False
        assert len(mock_llm_ok) == 0
        assert res["output"].startswith("# 自定义大模型节点")
        assert res["structured"]["query"] == "q"

    def test_agent_ref_tools_only_executes_tools_without_llm(
        self, db_path, engine, run_async, mock_profiles, mock_llm_ok, mock_tools
    ):
        """agent_ref 仅带 tools（无 model_profile）→ 执行工具但不调 LLM。"""
        reg = AgentRegistry()
        _register(reg, "ref-tools", tools=["tool-a"])
        input_params = {"agent_ref": "ref-tools", "query": "q"}
        res = run_async(engine._run_llm(_ctx(input_params), input_params, "real"))

        assert res["structured"]["agent_ref"] == "ref-tools"
        assert res["structured"]["used_llm"] is False
        assert len(mock_llm_ok) == 0
        assert res["structured"]["tools"] == ["tool-a"]
        assert any(e["type"] == "tool_call" and e["status"] == "success" for e in res["evidence"])
        assert res["output"].startswith("# 自定义大模型节点")
