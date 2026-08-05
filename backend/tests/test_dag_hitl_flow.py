"""T05-1 HITL 全链路集成测试（P0-1/2/3/4 核心验收）。

覆盖设计文档 §2.8 边界情形清单：
- DAG run 触发 HITL → approve → 真实处置执行 + run completed + 审批 approved（P0-4）
- DAG run 触发 HITL → reject → 不执行处置 + run completed + 无处置记录
- HITL 超时（mock 短超时）→ 审批 expired + stage failed + run failed（P0-1）
- cancel waiting_hitl run → 唤醒 + run cancelled（P2-6）
- HitlApproval.create 失败 → fail-safe 不等待 + run failed（P0-2）
- 审批端点：DAG run 创建后 GET /agents/approvals 可见（P0-2 回归：不再 404）
- orchestrator.resume mode=custom 委托 → resumed_by: pipeline_engine + run 最终 completed（P0-3）

测试库：conftest 提供的临时 SQLite + mock_llm，不真实调用 LLM。
"""

import asyncio
import json
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

from app.models.agent_run import AgentRun
from app.models.hitl_approval import HitlApproval
from app.services.agents.orchestrator import Orchestrator

_ADMIN = {"id": 1, "username": "admin", "role": "admin"}


def _build_client() -> TestClient:
    """最小 app：仅挂载 agents 路由 + admin 鉴权覆盖（不触发全量 startup）。"""
    app = FastAPI()
    app.include_router(agents_router, prefix="/api")
    app.dependency_overrides.clear()
    app.dependency_overrides[get_current_user] = lambda: _ADMIN
    return TestClient(app)


def _seed_security_event(event_id: str = "SE-1") -> None:
    """写入 cases → hosts → security_events（供 event_disposition_log FK 引用）。"""
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
            (event_id, host_id, json.dumps({"label": "suspicious", "reason": "beacon"})))
        conn.execute(
            "INSERT INTO normalized_logs "
            "(host_id, log_source, event_type, event_label, severity, timestamp, "
            "source_ip, process_name, command_line) "
            "VALUES (?, 'test', 'network', 'outbound', 'high', '2026-07-18 10:00:01', "
            "'8.8.8.8', 'powershell.exe', 'IWR http://8.8.8.8/x')", (host_id,))


def _base_ctx(run_id: str) -> dict:
    return {
        "run_id": run_id,
        "event_id": "SE-1",
        "user": {"id": 1, "username": "admin", "role": "admin"},
        "mode": "custom",
        "agent_names": ["triage", "responder"],
    }


async def _wait_waiting_hitl(engine, run_id: str, timeout: float = 5.0) -> None:
    """轮询等待 run 进入 waiting_hitl（超时抛断言）。"""
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        run_obj = engine.get_run(run_id)
        if run_obj and run_obj.status == "waiting_hitl":
            return
        await asyncio.sleep(0.02)
    raise AssertionError(f"run {run_id} 未在 {timeout}s 内进入 waiting_hitl")


# ──────────────────────────────────────────────────────────────
# 1. approve → 真实处置执行 + completed + 审批 approved
# ──────────────────────────────────────────────────────────────
def test_hitl_approve_executes_and_completes(db_path, engine, run_async, mock_llm):
    """DAG run 触发 HITL → approve → 执行真实处置 + run completed + 审批 approved。"""
    _seed_security_event("SE-1")
    run_id = f"qa_approve_{uuid.uuid4().hex[:8]}"
    ctx = _base_ctx(run_id)

    async def scenario():
        task = asyncio.create_task(
            engine.run(run_id, ["triage", "responder"], "SE-1", ctx, _ADMIN,
                       use_cache=False, ensure_reporter=True)
        )
        await _wait_waiting_hitl(engine, run_id)
        approvals = HitlApproval.list_by_run(run_id)
        assert len(approvals) == 1 and approvals[0]["status"] == "pending", approvals
        # 模拟 API approve 端点：update_status(approved) → engine.resume
        HitlApproval.update_status(approvals[0]["id"], HitlApproval.STATUS_APPROVED, decided_by=1)
        resumed = await engine.resume(run_id, approved=True, user=_ADMIN)
        assert resumed is True
        result = await asyncio.wait_for(task, timeout=20)
        return result, approvals[0]["id"]

    result, approval_id = run_async(scenario())
    # run 最终 completed
    assert result["status"] == "completed", result
    # DB run 状态 completed
    db_run = AgentRun.get_by_run_id(run_id)
    assert db_run and db_run["status"] == "completed"
    # 审批已 approved
    approvals = HitlApproval.list_by_run(run_id)
    assert approvals and approvals[0]["status"] == "approved"
    # 处置动作执行：hitl_decision approved + disposition log 有记录
    stage = next((s for s in result["stages"] if s["name"] == "responder"), None)
    assert stage is not None
    decision = (stage.get("output") or {}).get("hitl_decision", {})
    assert decision.get("status") == "approved", decision
    from app.database import get_connection
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM event_disposition_log WHERE event_id=?",
            ("SE-1",)).fetchone()
    assert row is not None, "approve 后应写 event_disposition_log"


# ──────────────────────────────────────────────────────────────
# 2. reject → 不执行处置 + completed + 无处置记录
# ──────────────────────────────────────────────────────────────
def test_hitl_reject_skips_action(db_path, engine, run_async, mock_llm):
    """DAG run 触发 HITL → reject → 不执行处置 + run completed + 无处置记录。"""
    _seed_security_event("SE-1")
    run_id = f"qa_reject_{uuid.uuid4().hex[:8]}"
    ctx = _base_ctx(run_id)

    async def scenario():
        task = asyncio.create_task(
            engine.run(run_id, ["triage", "responder"], "SE-1", ctx, _ADMIN,
                       use_cache=False, ensure_reporter=True)
        )
        await _wait_waiting_hitl(engine, run_id)
        approvals = HitlApproval.list_by_run(run_id)
        HitlApproval.update_status(approvals[0]["id"], HitlApproval.STATUS_REJECTED,
                                   decided_by=1, reason="误报")
        resumed = await engine.resume(run_id, approved=False, user=_ADMIN)
        assert resumed is True
        result = await asyncio.wait_for(task, timeout=20)
        return result

    result = run_async(scenario())
    assert result["status"] == "completed", result
    stage = next((s for s in result["stages"] if s["name"] == "responder"), None)
    decision = (stage.get("output") or {}).get("hitl_decision", {})
    assert decision.get("status") == "rejected", decision
    # 无处置记录
    from app.database import get_connection
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM event_disposition_log WHERE event_id=?",
            ("SE-1",)).fetchone()
    assert row is None, "reject 后不应写 event_disposition_log"


# ──────────────────────────────────────────────────────────────
# 3. 超时 → 审批 expired + stage failed + run failed
# ──────────────────────────────────────────────────────────────
def test_hitl_timeout_expires_and_fails(db_path, run_async, mock_llm):
    """HITL 超时（mock 短超时 0.2s）→ 审批 expired + stage failed + run failed。"""
    from app.services.agents.pipeline_engine import PipelineEngine
    engine = PipelineEngine()
    engine._HITL_WAIT_TIMEOUT = 0.2
    run_id = f"qa_timeout_{uuid.uuid4().hex[:8]}"
    ctx = _base_ctx(run_id)

    async def scenario():
        result = await engine.run(run_id, ["triage", "responder"], "SE-1", ctx, _ADMIN,
                                  use_cache=False, ensure_reporter=True)
        return result

    result = run_async(scenario())
    assert result["status"] == "failed", result
    responder_stage = next((s for s in result["stages"] if s["name"] == "responder"), None)
    assert responder_stage and responder_stage["status"] == "failed"
    assert responder_stage.get("error") == "hitl_timeout", responder_stage
    approvals = HitlApproval.list_by_run(run_id)
    assert approvals and approvals[0]["status"] == "expired", approvals


# ──────────────────────────────────────────────────────────────
# 4. cancel waiting_hitl → 唤醒 + run cancelled
# ──────────────────────────────────────────────────────────────
def test_cancel_waiting_hitl_wakes_and_cancels(db_path, engine, run_async, mock_llm):
    """cancel waiting_hitl run → event 唤醒（result=False）+ run cancelled。"""
    run_id = f"qa_cancel_{uuid.uuid4().hex[:8]}"
    ctx = _base_ctx(run_id)

    async def scenario():
        task = asyncio.create_task(
            engine.run(run_id, ["triage", "responder"], "SE-1", ctx, _ADMIN,
                       use_cache=False, ensure_reporter=True)
        )
        await _wait_waiting_hitl(engine, run_id)
        ok = engine.cancel(run_id)
        assert ok is True
        try:
            await asyncio.wait_for(task, timeout=15)
        except asyncio.TimeoutError:
            raise AssertionError("cancel 后 run 任务未结束")
        run_obj = engine.get_run(run_id)
        return run_obj

    run_obj = run_async(scenario())
    assert run_obj and run_obj.status == "cancelled", run_obj.status if run_obj else None
    # DB 状态同步
    db_run = AgentRun.get_by_run_id(run_id)
    assert db_run and db_run["status"] == "cancelled"


# ──────────────────────────────────────────────────────────────
# 5. HitlApproval.create 失败 → fail-safe 不等待 + run failed
# ──────────────────────────────────────────────────────────────
def test_hitl_approval_create_failure_failsafe(db_path, engine, run_async, mock_llm, monkeypatch):
    """HitlApproval.create 抛错 → fail-safe 不等待 + stage failed + run failed。"""
    run_id = f"qa_createfail_{uuid.uuid4().hex[:8]}"
    ctx = _base_ctx(run_id)

    def _boom(*args, **kwargs):
        raise RuntimeError("create failed")

    monkeypatch.setattr(HitlApproval, "create", staticmethod(_boom))

    async def scenario():
        # 不 create_task：fail-safe 应使 run 快速失败而不是挂起
        result = await engine.run(run_id, ["triage", "responder"], "SE-1", ctx, _ADMIN,
                                  use_cache=False, ensure_reporter=True)
        return result

    result = run_async(scenario())
    assert result["status"] == "failed", result
    responder_stage = next((s for s in result["stages"] if s["name"] == "responder"), None)
    assert responder_stage and responder_stage["status"] == "failed"
    assert responder_stage.get("error") == "hitl_approval_create_failed", responder_stage


# ──────────────────────────────────────────────────────────────
# 6. 审批端点可见性（P0-2 回归：不再 404）
# ──────────────────────────────────────────────────────────────
def test_approvals_endpoint_visible_after_dag_run(db_path, engine, run_async, mock_llm):
    """DAG run 创建审批记录后，GET /agents/approvals 可见（不再 404）。"""
    run_id = f"qa_approvallist_{uuid.uuid4().hex[:8]}"
    ctx = _base_ctx(run_id)

    async def scenario():
        task = asyncio.create_task(
            engine.run(run_id, ["triage", "responder"], "SE-1", ctx, _ADMIN,
                       use_cache=False, ensure_reporter=True)
        )
        await _wait_waiting_hitl(engine, run_id)
        # DAG run 已写审批记录（pending）→ 审批端点可见
        approvals = HitlApproval.list_by_run(run_id)
        assert len(approvals) == 1 and approvals[0]["status"] == "pending", approvals
        # 清理：取消 run，避免后台任务悬挂（审批记录保持 pending，端点仍可见）
        engine.cancel(run_id)
        await asyncio.wait_for(task, timeout=15)
        return run_id

    run_id = run_async(scenario())
    client = _build_client()
    with client:
        resp = client.get("/api/agents/approvals")
        assert resp.status_code == 200, resp.text
        items = resp.json()["data"]["items"]
        assert any(it["run_id"] == run_id for it in items), items


# ──────────────────────────────────────────────────────────────
# 7. orchestrator.resume mode=custom 委托 → resumed_by: pipeline_engine
# ──────────────────────────────────────────────────────────────
def test_orchestrator_resume_delegates_custom_mode(db_path, engine, run_async, mock_llm, monkeypatch):
    """orchestrator.resume 对 mode=custom 委托 pipeline_engine.resume；
    返回 resumed_by: pipeline_engine + run 最终 completed。"""
    # 关键：orchestrator.resume 函数级 import pipeline_engine 单例，
    # 这里 monkeypatch 模块属性，使委托命中测试引擎实例。
    import app.services.agents.pipeline_engine as pe_module
    monkeypatch.setattr(pe_module, "pipeline_engine", engine)

    _seed_security_event("SE-1")
    run_id = f"qa_delegate_{uuid.uuid4().hex[:8]}"
    ctx = _base_ctx(run_id)
    orch = Orchestrator()

    async def scenario():
        task = asyncio.create_task(
            engine.run(run_id, ["triage", "responder"], "SE-1", ctx, _ADMIN,
                       use_cache=False, ensure_reporter=True)
        )
        await _wait_waiting_hitl(engine, run_id)
        approvals = HitlApproval.list_by_run(run_id)
        HitlApproval.update_status(approvals[0]["id"], HitlApproval.STATUS_APPROVED, decided_by=1)
        approval = HitlApproval.get_by_id(approvals[0]["id"])
        outcome = await orch.resume(run_id, approval, decided_by=1, user=_ADMIN)
        result = await asyncio.wait_for(task, timeout=20)
        return outcome, result

    outcome, result = run_async(scenario())
    assert outcome.get("resumed_by") == "pipeline_engine", outcome
    assert outcome.get("status") == "running", outcome
    assert result["status"] == "completed", result
    db_run = AgentRun.get_by_run_id(run_id)
    assert db_run and db_run["status"] == "completed"
