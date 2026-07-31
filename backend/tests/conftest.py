"""pytest 共享 fixture — DAG 流水线修复测试（T01 基础设施）。

提供：
- ``db_path``（function）：独立临时 SQLite + 建表 + 预置 Agent 种子，
  测试结束后恢复原 ``settings.DB_PATH``，不污染其它测试；
- ``engine``（function）：每用例独立 ``PipelineEngine`` 实例（构造不触 DB）；
- ``run_async``：同步包装协程的辅助；
- ``mock_llm``：禁用真实 LLM 调用（降级合成响应）。

注意：所有 fixture 均非 autouse，不影响既有测试的 DB_PATH 自管理。
"""

import asyncio
import os
import sys
import uuid
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _init_test_db(path: str) -> None:
    """设置 ``settings.DB_PATH`` 并建表 + 注入预置 Agent（幂等）。"""
    from app.config import settings
    settings.DB_PATH = path
    Path(settings.DATA_DIR).mkdir(parents=True, exist_ok=True)
    from app.database import init_db
    init_db()
    # 注入预置 Agent（seed_preset_agents 逐条检查 DB，可重复执行；
    # 不用 AgentRegistry.init()，避免单例 _initialized 标志跨库失效）
    from app.services.agents.agent_registry import AgentRegistry
    from app.services.agents.preset_data import seed_preset_agents
    try:
        seed_preset_agents(AgentRegistry())
    except Exception:
        # 种子失败不阻断测试（用例可自行注册 Agent）
        pass


@pytest.fixture()
def db_path():
    """function-scoped 临时 SQLite；结束后恢复原 DB_PATH，避免污染其它测试。

    使用唯一文件名（``test_dag_fix_<hex>.db``），规避沙箱 safe-delete 问题。
    """
    from app.config import settings
    original = settings.DB_PATH
    data_dir = BACKEND_DIR / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    path = str(data_dir / f"test_dag_fix_{uuid.uuid4().hex[:8]}.db")
    _init_test_db(path)
    yield path
    settings.DB_PATH = original
    # 尽力清理临时库及其 WAL/SHM 附属文件
    for suffix in ("", "-wal", "-shm"):
        try:
            if os.path.exists(path + suffix):
                os.remove(path + suffix)
        except OSError:
            pass


@pytest.fixture()
def engine(db_path):
    """每用例独立 PipelineEngine 实例（构造不触 DB，P2-4）。"""
    from app.services.agents.pipeline_engine import PipelineEngine
    return PipelineEngine()


@pytest.fixture()
def run_async():
    """返回同步执行协程的辅助函数：``run_async(coro) -> result``。"""
    def _run(coro):
        return asyncio.run(coro)
    return _run


@pytest.fixture()
def mock_llm(monkeypatch):
    """禁用真实 LLM 调用：将 ``AgentLLM`` 替换为降级合成实现。

    通过 monkeypatch 模块属性，函数级 ``from app.services.agent_llm import
    AgentLLM`` 在调用时读取到的是替换后的类。
    """
    from app.services import agent_llm as agent_llm_module

    class _FakeLLM:
        async def call(self, prompt, user=None, trace_id=None, **kwargs):
            return {"content": "（测试合成响应）", "degraded": True}

    monkeypatch.setattr(agent_llm_module, "AgentLLM", _FakeLLM)
    return _FakeLLM
