"""T05-3 稳健性测试（P2-3/4/5/6）。

覆盖：
- 模块导入不触 DB（P2-4）：import 断言 + 无 DB 查询日志
- waiting_hitl 清理（P2-3）：mock 短 TTL 后过期 → 审批 expired + DB failed
- SSE 回调异常被记录而非吞掉（P2-5）
- 取消语义（P2-6）：cancel in-flight 节点

测试库：conftest 提供的临时 SQLite，不真实调用 LLM。
"""

import asyncio
import logging
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.models.agent_run import AgentRun
from app.models.hitl_approval import HitlApproval
from app.services.agents.agent_definition import AgentDefinition
from app.services.agents.agent_registry import AgentRegistry
from app.services.agents.pipeline_common import _safe_sse

_ADMIN = {"id": 1, "username": "admin", "role": "admin"}


def _register(reg, name, display, depends_on=None, config=None, hitl=False):
    try:
        reg.register(AgentDefinition(
            name=name, display_name=display, type="custom",
            depends_on=depends_on or [], config=config or {}, hitl=hitl,
        ))
    except ValueError:
        pass


# ──────────────────────────────────────────────────────────────
# P2-4: 模块导入不触 DB
# ──────────────────────────────────────────────────────────────
def test_module_import_no_db():
    """导入 pipeline_engine 模块不触 DB（懒初始化）：import 断言。"""
    # 子进程隔离导入，确保在全新解释器下构造模块级单例
    code = (
        "import sys; sys.path.insert(0, r'%s'); "
        "from app.services.agents.pipeline_engine import PipelineEngine, pipeline_engine; "
        "e = PipelineEngine(); "
        "assert e._restored is False, 'construction must not restore'; "
        "print('IMPORT_OK')"
    ) % str(BACKEND_DIR)
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert "IMPORT_OK" in proc.stdout


def test_engine_construction_no_db_query(db_path, run_async, caplog):
    """构造 PipelineEngine 不触发 DB 查询（无 SELECT 日志）。"""
    from app.services.agents.pipeline_engine import PipelineEngine
    with caplog.at_level(logging.DEBUG, logger="app.services.agents.pipeline_engine"):
        engine = PipelineEngine()
    # 构造期不应有任何 DB 查询日志（_restore_hitl_events 为懒加载）
    db_logs = [r for r in caplog.records if "SELECT" in r.getMessage() or "restore" in r.getMessage().lower()]
    assert engine._restored is False
    assert not db_logs, db_logs


# ──────────────────────────────────────────────────────────────
# P2-3: waiting_hitl 清理
# ──────────────────────────────────────────────────────────────
def test_waiting_hitl_cleanup_expires(db_path, engine):
    """_cleanup_expired_runs 对超 TTL 的 waiting_hitl run：
    审批置 expired + DB status=failed + 内存清理。"""
    from app.services.agents.pipeline_engine import PipelineRun
    run_id = f"qa_cleanup_{uuid.uuid4().hex[:8]}"
    # 预置 DB 记录（waiting_hitl）
    AgentRun.create(run_id=run_id, event_id="SE-1", stage="responder",
                    status="waiting_hitl", ctx_json='{"mode": "custom"}')
    approval = HitlApproval.create(run_id=run_id, action="custom")

    # 内存 run：status=waiting_hitl，start_time 远早于 TTL
    run = PipelineRun(run_id, ["responder"], "SE-1", {})
    run.status = "waiting_hitl"
    run.start_time = time.time() - 100
    engine._runs[run_id] = run
    engine._HITL_EXPIRE_TTL = 10  # 100s > 10s → 过期

    n = engine._cleanup_expired_runs()
    assert n == 1
    # 审批 expired
    ap = HitlApproval.get_by_id(approval["id"])
    assert ap and ap["status"] == "expired", ap
    # DB status failed
    db_run = AgentRun.get_by_run_id(run_id)
    assert db_run and db_run["status"] == "failed", db_run
    # 内存清理
    assert run_id not in engine._runs


# ──────────────────────────────────────────────────────────────
# P2-5: SSE 回调异常被记录而非吞掉
# ──────────────────────────────────────────────────────────────
def test_safe_sse_logs_callback_exception(caplog):
    """_safe_sse 内回调异常 → logger.exception 记录，不向上抛。"""
    async def _bad(evt, data):
        raise RuntimeError("sse boom")

    with caplog.at_level(logging.ERROR, logger="app.services.agents.pipeline_common"):
        asyncio.run(_safe_sse(_bad, "test", {}))
    assert any("PipelineEngine SSE 回调异常" in r.getMessage() for r in caplog.records), caplog.records


def test_run_with_raising_sse_callback_continues(db_path, engine, run_async, mock_llm, caplog):
    """引擎 run 中 SSE 回调抛异常 → 主流程不中断，异常被记录。"""
    run_id = f"qa_sse_{uuid.uuid4().hex[:8]}"
    ctx = {"run_id": run_id, "event_id": "SE-1", "user": {"id": 1}, "mode": "custom",
           "agent_names": ["triage"]}

    async def _bad_sse(evt, data):
        raise RuntimeError("sse boom")

    async def scenario():
        return await engine.run(run_id, ["triage"], "SE-1", ctx, {"id": 1},
                                use_cache=False, ensure_reporter=False, on_sse=_bad_sse)

    with caplog.at_level(logging.ERROR, logger="app.services.agents.pipeline_common"):
        result = run_async(scenario())
    # 主流程正常完成
    assert result["status"] == "completed", result
    # 回调异常已记录（未被静默吞掉）
    assert any("PipelineEngine SSE 回调异常" in r.getMessage() for r in caplog.records), caplog.records


# ──────────────────────────────────────────────────────────────
# P2-6: cancel in-flight 节点
# ──────────────────────────────────────────────────────────────
def test_cancel_in_flight_node(db_path, engine, run_async, mock_llm, monkeypatch):
    """cancel 中断 in-flight 节点：stage cancelled + run cancelled。"""
    reg = AgentRegistry()
    _register(reg, "llm", "LLM 节点")

    async def _slow_runner(ctx, input_params, mode):
        await asyncio.sleep(30)
        return {"stage": "llm", "output": "done"}

    # 让 llm 节点变慢（模拟 in-flight）
    monkeypatch.setattr(engine, "_run_llm", _slow_runner)

    run_id = f"qa_inflight_{uuid.uuid4().hex[:8]}"
    ctx = {"run_id": run_id, "event_id": "SE-1", "user": {"id": 1}, "mode": "custom",
           "agent_names": ["llm"]}

    async def scenario():
        task = asyncio.create_task(
            engine.run(run_id, ["llm"], "SE-1", ctx, {"id": 1},
                       use_cache=False, ensure_reporter=False)
        )
        await asyncio.sleep(0.2)  # 等节点进入执行
        ok = engine.cancel(run_id)
        assert ok is True
        try:
            await asyncio.wait_for(task, timeout=10)
        except asyncio.TimeoutError:
            raise AssertionError("cancel in-flight 后 run 任务未结束")
        return engine.get_run(run_id)

    run_obj = run_async(scenario())
    assert run_obj and run_obj.status == "cancelled", run_obj.status if run_obj else None
    llm_stage = next((s for s in run_obj.stages if s["name"] == "llm"), None)
    assert llm_stage and llm_stage["status"] == "cancelled", run_obj.stages
