"""P0/P1 测试共享 fixture — mock AgentLLM / ToolRegistry.call_tool / AiConfigProfile。

设计依据：``custom-agent/design.md`` T02（``helpers/agent_test_utils.py``）。

本模块提供的 fixture 被 ``test_p0_custom_agent_real_execution.py`` 与
``test_p1_llm_agent_ref.py`` 显式导入使用（pytest 允许从测试模块导入
``@pytest.fixture`` 装饰函数并参与解析）：

- ``fake_profiles``：AiConfigProfile mock 数据（id=1 激活 / id=2 备用）。
- ``mock_profiles``：把 ``AiConfigProfile.get_by_id/list_all/get_active`` 替换为
  上述数据（``_resolve_llm_profile`` 依赖）。
- ``mock_llm_ok``：把 ``app.services.agent_llm.AgentLLM`` 替换为成功实现
  （``degraded=False`` + content），记录每次调用（prompt/user/profile）。
- ``mock_tools``：把 ``ToolRegistry.call_tool`` 替换为可覆写 handler 的实现
  （默认成功；测试可通过 ``state["handler"]`` 注入失败/异常/超时）。

所有 fixture 均非 autouse，仅被显式请求的用例生效。
"""

import pytest

from app.models.ai_config import AiConfigProfile
from app.services import agent_llm as agent_llm_module
from app.services.mcp.registry import ToolRegistry


@pytest.fixture()
def fake_profiles():
    """AiConfigProfile mock 数据：id=1 激活，id=2 备用。"""
    return {
        1: {"id": 1, "profile_name": "默认配置", "model_name": "gpt-4o", "is_active": 1, "api_key": "k"},
        2: {"id": 2, "profile_name": "备用配置", "model_name": "deepseek", "is_active": 0, "api_key": "k2"},
    }


@pytest.fixture()
def mock_profiles(monkeypatch, fake_profiles):
    """将 AiConfigProfile 三个静态方法替换为 fake_profiles 数据。"""
    monkeypatch.setattr(AiConfigProfile, "get_by_id", staticmethod(lambda pid: fake_profiles.get(int(pid))))
    monkeypatch.setattr(AiConfigProfile, "list_all", staticmethod(lambda: list(fake_profiles.values())))
    monkeypatch.setattr(AiConfigProfile, "get_active", staticmethod(lambda: fake_profiles.get(1)))
    return fake_profiles


@pytest.fixture()
def mock_llm_ok(monkeypatch):
    """成功 LLM：degraded=False + content；记录每次调用。

    Returns:
        list[dict]: 每次调用记录 ``{"prompt", "user", "profile"}``。
    """
    calls = []

    class FakeLLM:
        def __init__(self, profile=None):
            self.profile = profile

        async def call(self, prompt, user=None, trace_id=None, **kwargs):
            calls.append({"prompt": prompt, "user": user, "profile": self.profile})
            return {"content": f"__LLM_CONTENT__:{prompt[:20]}", "degraded": False, "usage": {}}

    monkeypatch.setattr(agent_llm_module, "AgentLLM", FakeLLM)
    return calls


@pytest.fixture()
def mock_tools(monkeypatch):
    """工具注册表 mock：默认成功；可通过 ``state["handler"]`` 覆写行为。

    Returns:
        dict: ``{"handler": Optional[Callable[[tool_id, args], dict]]}``。
    """
    state = {"handler": None}

    def _fake(tool_id, args):
        if state["handler"] is not None:
            return state["handler"](tool_id, args)
        return {"ok": True, "tool_id": tool_id, "result": f"result-{tool_id}"}

    monkeypatch.setattr(ToolRegistry, "call_tool", staticmethod(_fake))
    return state
