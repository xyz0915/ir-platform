"""阶段一（轻量打通）测试套件 — event_type 保留 + source 标记 + analyze 门禁放宽.

覆盖范围：
- agent.agent._collect_incremental：保留原始 event_type、新增 source=采集器名
  （修复 event_type 被整体覆盖导致 process_events 表失去 process_start、归一化/根因捞不到）。
- app.models.process_event.ProcessEvent：source 列落库与查询。
- app.api.analysis.analyze_host：门禁放宽——常驻 daemon 主机（有已注册 Agent 或
  实时进程事件）即使 status=pending 也允许触发分析；完全空主机仍拒绝。

DB 隔离（重要）：module-scoped 临时 SQLite（系统 temp 目录，不落 backend/data），
init_db() 仅建库一次；每用例前清空被测表，保证隔离且不污染真实库。
"""

import os
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

# agent 包内的 collectors/utils 以顶层包方式被 agent.py 引用，
# 因此需把 agent/ 目录本身加入 sys.path（而非仓库根）
_ROOT = _BACKEND.parent
_AGENT_DIR = _ROOT / "agent"
if str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import init_db, get_connection  # noqa: E402

_TABLES_TO_CLEAR = ["process_events", "audit_logs", "agents", "hosts", "cases"]


def _clear_data() -> None:
    with get_connection() as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        for t in _TABLES_TO_CLEAR:
            conn.execute(f"DELETE FROM {t}")
        conn.execute("PRAGMA foreign_keys = ON")


@pytest.fixture(scope="module")
def env():
    original = settings.DB_PATH
    original_jm = getattr(settings, "DB_JOURNAL_MODE", "WAL")
    tmp_dir = tempfile.mkdtemp(prefix="phase1_")
    db_path = str(Path(tmp_dir) / "test.db")
    settings.DB_PATH = db_path
    settings.DB_JOURNAL_MODE = "DELETE"
    init_db()

    from app.models.user import User
    from app.services.auth_service import create_token
    user = User.get_by_username("admin")
    assert user is not None
    jwt = create_token(user)
    headers = {"Authorization": f"Bearer {jwt}"}

    from app.api.agents import router as agents_router
    from app.api.process_events import router as pe_router
    from app.api.analysis import router as analysis_router

    app = FastAPI()
    app.include_router(agents_router, prefix="/api")
    app.include_router(pe_router, prefix="/api")
    app.include_router(analysis_router, prefix="/api")

    ctx = {"db_path": db_path, "tmp_dir": tmp_dir, "jwt": jwt,
           "headers": headers, "user": user, "app": app}
    yield ctx

    settings.DB_PATH = original
    settings.DB_JOURNAL_MODE = original_jm
    import shutil
    shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.fixture()
def client(env):
    with TestClient(env["app"]) as c:
        _clear_data()
        yield c


def seed_host(status="pending", hostname="hostA") -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO cases (name) VALUES (?)", [f"QA-{uuid.uuid4().hex[:8]}"]
        )
        case_id = int(cur.lastrowid)
        cur = conn.execute(
            "INSERT INTO hosts (case_id, hostname, status) VALUES (?, ?, ?)",
            [case_id, hostname, status],
        )
        return int(cur.lastrowid)


# ============================================================================
# 1) agent._collect_incremental：保留 event_type + 新增 source
# ============================================================================

class _FakeCollector:
    def is_supported(self):
        return True

    def collect(self):
        return [
            {"event_type": "process_start", "pid": 100, "process_name": "cmd.exe"},
            {"event_type": "process_exit", "pid": 100, "process_name": "cmd.exe"},
        ]


def test_collect_incremental_preserves_event_type_and_sets_source(monkeypatch):
    import agent as agent_mod
    monkeypatch.setattr(agent_mod, "load_collector", lambda name: _FakeCollector())
    events = agent_mod._collect_incremental(["process_events"], {})
    assert len(events) == 2
    for e in events:
        assert e["source"] == "process_events", "应新增 source=采集器名"
        assert e["event_type"] in ("process_start", "process_exit"), \
            "原始 event_type 不应被覆盖"


def test_collect_incremental_overwrite_regression(monkeypatch):
    """回归：确保不再把 event_type 改写为采集器名（即不等于 'process_events'）。"""
    import agent as agent_mod
    monkeypatch.setattr(agent_mod, "load_collector", lambda name: _FakeCollector())
    events = agent_mod._collect_incremental(["process_events"], {})
    assert all(e["event_type"] != "process_events" for e in events)


# ============================================================================
# 2) ProcessEvent 模型：source 列落库
# ============================================================================

def test_process_event_source_persisted():
    from app.models.process_event import ProcessEvent
    host_id = seed_host(status="imported")
    ProcessEvent.create(host_id=host_id, event_type="process_start", pid=5,
                        process_name="cmd.exe", source="process_events")
    rows = ProcessEvent.list_by_host_and_type(host_id, "process_start")
    assert rows, "process_start 事件应可被 list 查询（供归一化/根因）"
    assert rows[0]["source"] == "process_events"


def test_list_process_starts_picks_daemon_events():
    """daemon 推进来的 process_start 事件应进入 list_process_starts（根因数据源）。"""
    from app.models.process_event import ProcessEvent
    host_id = seed_host(status="imported")
    ProcessEvent.create(host_id=host_id, event_type="process_start", pid=7,
                        process_name="powershell.exe", source="process_events")
    starts = ProcessEvent.list_process_starts(host_id)
    assert len(starts) == 1 and starts[0]["source"] == "process_events"


# ============================================================================
# 3) analyze_host 门禁放宽
# ============================================================================

def test_analyze_rejects_empty_pending_host(client, env):
    host_id = seed_host(status="pending")
    resp = client.post(f"/api/hosts/{host_id}/analyze", headers=env["headers"])
    assert resp.status_code == 400
    assert "无法分析" in resp.json().get("detail", "")


def test_analyze_allows_pending_host_with_events(client, env):
    """有实时进程事件的 pending 主机应通过门禁（analyze 本身可能因无快照数据报错，但不影响门禁验证）。"""
    from app.models.process_event import ProcessEvent
    host_id = seed_host(status="pending")
    ProcessEvent.create(host_id=host_id, event_type="process_start", pid=9,
                        process_name="cmd.exe", source="process_events")
    resp = client.post(f"/api/hosts/{host_id}/analyze", headers=env["headers"])
    assert "无法分析" not in resp.json().get("detail", ""), \
        "门禁应放行：有实时进程事件的常驻主机允许分析"


def test_analyze_allows_pending_host_with_registered_agent(client, env):
    """有已注册 Agent（token_set）的 pending 主机应通过门禁。"""
    host_id = seed_host(status="pending")
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO agents (host_id, agent_id, status, token_hash) VALUES (?, ?, 'online', 'x')",
            [host_id, f"agent-{uuid.uuid4().hex[:8]}"],
        )
    resp = client.post(f"/api/hosts/{host_id}/analyze", headers=env["headers"])
    assert "无法分析" not in resp.json().get("detail", ""), \
        "门禁应放行：有已注册 Agent 的常驻主机允许分析"
