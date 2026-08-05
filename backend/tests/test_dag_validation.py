"""T05-2 校验与执行正确性测试（P1-1/2/4 + P2-1/2）。

覆盖：
- 有环 DAG → create_agent_run 返 400；引擎内兜底 failed（P1-1）
- input_params 透传：节点级配置 + run 级 ctx 覆盖（用 llm 节点断言 query/prompt_used）（P1-2）
- guardrail：默认放行 + 显式 block 阻断 + simulate fixture（P1-4）
- compute_final_status 纯函数：cancelled > failed > waiting_hitl > completed（P1-3）
- 缓存键：同 event + 不同 input_params 不互相命中（P2-1）

测试库：conftest 提供的临时 SQLite，不真实调用 LLM。
"""

import asyncio
import sys
import uuid
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.agents import router as agents_router
from app.services.auth_service import get_current_user

from app.models.agent_definition import PipelinePresetModel
from app.services.agents.agent_definition import AgentDefinition
from app.services.agents.agent_registry import AgentRegistry
from app.services.agents.cache_manager import CacheManager
from app.services.agents.pipeline_common import compute_final_status, _stable_dict
from app.services.agents.pipeline_engine import PipelineRun

_ADMIN = {"id": 1, "username": "admin", "role": "admin"}


def _build_client() -> TestClient:
    app = FastAPI()
    app.include_router(agents_router, prefix="/api")
    app.dependency_overrides.clear()
    app.dependency_overrides[get_current_user] = lambda: _ADMIN
    return TestClient(app)


def _register(reg, name, display, depends_on=None, config=None, hitl=False):
    try:
        reg.register(AgentDefinition(
            name=name, display_name=display, type="custom",
            depends_on=depends_on or [], config=config or {}, hitl=hitl,
        ))
    except ValueError:
        pass  # 已注册（幂等）


# ──────────────────────────────────────────────────────────────
# P1-1: 环检测
# ──────────────────────────────────────────────────────────────
def test_cycle_detected_by_validate_pipeline(db_path):
    """register 两个互相依赖的 agent 形成环 → validate_pipeline 返回 Circular。"""
    reg = AgentRegistry()
    _register(reg, "cycle_a", "A", depends_on=["cycle_b"])
    _register(reg, "cycle_b", "B", depends_on=["cycle_a"])
    msgs = reg.validate_pipeline(["cycle_a", "cycle_b"])
    assert any("Circular" in m for m in msgs), msgs


def test_cycle_create_agent_run_returns_400(db_path):
    """create_agent_run 对含环 DAG 同步返 400（P1-1 API 层）。"""
    reg = AgentRegistry()
    _register(reg, "cycle_a", "A", depends_on=["cycle_b"])
    _register(reg, "cycle_b", "B", depends_on=["cycle_a"])
    preset = PipelinePresetModel.create({"name": "cycle_preset", "agents": ["cycle_a", "cycle_b"]})

    client = _build_client()
    with client:
        resp = client.post("/api/agents/run", json={"preset_id": preset["id"]})
        assert resp.status_code == 400, resp.text
        assert "Circular" in resp.json()["detail"], resp.json()


def test_cycle_engine_fallback_failed(db_path, engine, run_async, mock_llm):
    """引擎内兜底：有环 DAG → run failed（错误信息可见，不静默丢节点）。"""
    reg = AgentRegistry()
    _register(reg, "cycle_a", "A", depends_on=["cycle_b"])
    _register(reg, "cycle_b", "B", depends_on=["cycle_a"])
    run_id = f"qa_cycle_{uuid.uuid4().hex[:8]}"
    ctx = {"run_id": run_id, "event_id": "SE-1", "user": {"id": 1}, "mode": "custom",
           "agent_names": ["cycle_a", "cycle_b"]}

    async def scenario():
        return await engine.run(run_id, ["cycle_a", "cycle_b"], "SE-1", ctx, {"id": 1},
                                use_cache=False, ensure_reporter=False)

    result = run_async(scenario())
    assert result["status"] == "failed", result
    assert "环" in result.get("error", ""), result


# ──────────────────────────────────────────────────────────────
# P1-2: input_params 透传
# ──────────────────────────────────────────────────────────────
def test_input_params_passthrough(db_path, engine, run_async, mock_llm):
    """input_params 透传：run 级覆盖节点级 query；prompt 保留节点级。"""
    reg = AgentRegistry()
    _register(reg, "llm", "LLM", config={"input_params": {
        "prompt": "节点级 prompt", "query": "节点级 query"}})
    run_id = f"qa_ip_{uuid.uuid4().hex[:8]}"
    ctx = {"run_id": run_id, "event_id": "SE-1", "user": {"id": 1}, "mode": "custom",
           "agent_names": ["llm"], "input_params": {"query": "run 级 query"}}

    async def scenario():
        return await engine.run(run_id, ["llm"], "SE-1", ctx, {"id": 1},
                                use_cache=False, ensure_reporter=False)

    result = run_async(scenario())
    assert result["status"] == "completed", result
    stage = next((s for s in result["stages"] if s["name"] == "llm"), None)
    structured = (stage or {}).get("output", {}).get("structured", {})
    assert structured.get("query") == "run 级 query", structured
    assert structured.get("prompt_used") == "节点级 prompt", structured


# ──────────────────────────────────────────────────────────────
# P1-4: Guardrail
# ──────────────────────────────────────────────────────────────
def test_guardrail_default_pass(db_path, engine, run_async, mock_llm):
    """guardrail 节点：默认放行（记录，不阻断）。"""
    reg = AgentRegistry()
    _register(reg, "guard_demo", "门禁")
    async def scenario():
        return await engine.execute_node("guardrail", "guard_demo", {"checks": [{"rule": "r1"}]}, {}, "real", {})
    res = run_async(scenario())
    assert res["status"] == "success", res
    assert res["result"]["structured"]["blocked"] is False


def test_guardrail_explicit_block(db_path, engine, run_async, mock_llm):
    """guardrail 节点：显式 block=true 阻断。"""
    reg = AgentRegistry()
    _register(reg, "guard_demo", "门禁")
    async def scenario():
        return await engine.execute_node("guardrail", "guard_demo",
                                         {"block": True, "reason": "高危"}, {}, "real", {})
    res = run_async(scenario())
    # execute_node 顶层 status 保持 success（不抛 500），structured.blocked=True 反映阻断
    assert res["result"]["structured"]["blocked"] is True, res
    assert res["result"]["structured"]["checks"][0]["passed"] is False


def test_guardrail_simulate_fixture(db_path, engine, run_async, mock_llm):
    """guardrail 节点 simulate fixture。"""
    reg = AgentRegistry()
    _register(reg, "guard_demo", "门禁")
    async def scenario():
        return await engine.execute_node("guardrail", "guard_demo", {}, {}, "simulate", {})
    res = run_async(scenario())
    assert res["status"] == "success", res


# ──────────────────────────────────────────────────────────────
# P1-3: compute_final_status 纯函数
# ──────────────────────────────────────────────────────────────
def test_compute_final_status_priority():
    """优先级：cancelled > failed > waiting_hitl > completed。"""
    r = PipelineRun("r1", ["a"], "e1", {})
    assert compute_final_status(r) == "completed"
    r.stages.append({"name": "a", "status": "waiting_hitl"})
    assert compute_final_status(r) == "waiting_hitl"
    r.stages.append({"name": "b", "status": "failed"})
    assert compute_final_status(r) == "failed"
    r.cancelled = True
    assert compute_final_status(r) == "cancelled"


def test_stable_dict_normalizes_order():
    """_stable_dict：结构归一化（缓存键稳定性）。"""
    s1 = _stable_dict({"b": 2, "a": [1, {"x": 1}]})
    s2 = _stable_dict({"a": [1, {"x": 1}], "b": 2})
    assert s1 == s2


# ──────────────────────────────────────────────────────────────
# P2-1: 缓存键含 input_params
# ──────────────────────────────────────────────────────────────
def test_cache_key_distinguishes_input_params(db_path, run_async, mock_llm):
    """同 event + 不同 input_params 不互相命中；相同 input_params 命中。"""
    from app.services.agents.pipeline_engine import PipelineEngine
    engine = PipelineEngine()
    engine._cache = CacheManager()  # 独立缓存，避免跨测试污染
    reg = AgentRegistry()
    _register(reg, "llm", "LLM", config={"input_params": {"prompt": "p"}})
    evt = f"EVT-{uuid.uuid4().hex[:8]}"

    def _run(run_id, query):
        ctx = {"run_id": run_id, "event_id": evt, "user": {"id": 1}, "mode": "custom",
               "agent_names": ["llm"], "input_params": {"query": query}}
        async def scenario():
            return await engine.run(run_id, ["llm"], evt, ctx, {"id": 1},
                                    use_cache=True, ensure_reporter=False)
        return run_async(scenario())

    r1 = _run(f"qa_c1_{uuid.uuid4().hex[:8]}", "query-1")
    r2 = _run(f"qa_c2_{uuid.uuid4().hex[:8]}", "query-2")
    r3 = _run(f"qa_c3_{uuid.uuid4().hex[:8]}", "query-1")  # 与 r1 相同 input_params

    def _cached(res):
        stage = next((s for s in res["stages"] if s["name"] == "llm"), None)
        return bool(stage and stage.get("cached"))

    assert _cached(r1) is False
    assert _cached(r2) is False       # 不同 input_params → 不命中
    assert _cached(r3) is True        # 相同 input_params → 命中
