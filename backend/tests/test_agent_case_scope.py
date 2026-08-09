"""主机 Agent「案件维度收敛」测试 — 方案 B.

验证 backend/app/api/agents.py 的 list_agents / get_agent_stats 在传入 case_id 时
仅返回该案件下的主机 agent；不传时保持全平台（兼容既有全局视图）。

DB 隔离：module-scoped 临时 SQLite，init_db() 仅建库一次；每用例前清空被测表。
"""

import sys
import uuid
import tempfile
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

_ROOT = _BACKEND.parent
_AGENT_DIR = _ROOT / "agent"
if str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import init_db, get_connection  # noqa: E402

_TABLES_TO_CLEAR = [
    "process_events", "file_hashes", "network_connections",
    "triage_tasks", "agents", "hosts", "cases",
]


def _clear_data() -> None:
    with get_connection() as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        for t in _TABLES_TO_CLEAR:
            try:
                conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        conn.execute("PRAGMA foreign_keys = ON")


@pytest.fixture(scope="module")
def env():
    original = settings.DB_PATH
    original_jm = getattr(settings, "DB_JOURNAL_MODE", "WAL")
    tmp_dir = tempfile.mkdtemp(prefix="agent_case_")
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
    app = FastAPI()
    app.include_router(agents_router, prefix="/api")

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


def seed_case(name):
    """插入一个案件，返回 case_id。"""
    with get_connection() as conn:
        cur = conn.execute("INSERT INTO cases (name) VALUES (?)", [name])
        return int(cur.lastrowid)


def seed_host(case_id, hostname, agent_online=None):
    """在指定案件下插入主机，返回 host_id。

    agent_online:
      - None : 不插入 agents 行（主机存在但无 agent）
      - True : 插入 agents 行且 last_heartbeat=now（在线）
      - False: 插入 agents 行且 last_heartbeat=now-10h（离线）
    """
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO hosts (case_id, hostname, status) VALUES (?, ?, 'imported')",
            [case_id, hostname],
        )
        host_id = int(cur.lastrowid)
        if agent_online is not None:
            hb = "datetime('now')" if agent_online else "datetime('now', '-10 hours')"
            conn.execute(
                "INSERT INTO agents (host_id, agent_id, agent_version, last_heartbeat) "
                "VALUES (?, ?, '1.0', " + hb + ")",
                [host_id, f"agent-{uuid.uuid4().hex[:12]}"],
            )
        return host_id


def test_list_all_without_case_id_returns_every_host(client, env):
    caseA = seed_case("caseA")
    seed_host(caseA, "host-1", agent_online=True)
    seed_host(caseA, "host-2", agent_online=False)
    caseB = seed_case("caseB")
    seed_host(caseB, "host-3", agent_online=True)

    resp = client.get("/api/agents", headers=env["headers"])
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["total"] == 3, "不传 case_id 应返回全平台 3 台"
    assert len(data["items"]) == 3


def test_list_filter_by_case_id_returns_only_that_case(client, env):
    caseA = seed_case("caseA")
    h1 = seed_host(caseA, "host-1", agent_online=True)
    h2 = seed_host(caseA, "host-2", agent_online=False)
    caseB = seed_case("caseB")
    seed_host(caseB, "host-3", agent_online=True)

    resp = client.get(f"/api/agents?case_id={caseA}", headers=env["headers"])
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["total"] == 2, "应按 case_id 收敛为 2 台"
    got_hosts = {it["host_id"] for it in data["items"]}
    assert got_hosts == {h1, h2}, "应仅含该案件下的主机"


def test_list_filter_other_case_isolated(client, env):
    caseA = seed_case("caseA")
    seed_host(caseA, "host-1", agent_online=True)
    caseB = seed_case("caseB")
    h3 = seed_host(caseB, "host-3", agent_online=True)

    resp = client.get(f"/api/agents?case_id={caseB}", headers=env["headers"])
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["host_id"] == h3


def test_list_host_without_agent_still_listed(client, env):
    caseA = seed_case("caseA")
    h1 = seed_host(caseA, "host-no-agent", agent_online=None)

    resp = client.get(f"/api/agents?case_id={caseA}", headers=env["headers"])
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["total"] == 1, "无 agent 的主机也应展示（LEFT JOIN）"
    assert data["items"][0]["token_set"] is False
    assert data["items"][0]["host_id"] == h1


def test_stats_all_without_case_id(client, env):
    caseA = seed_case("caseA")
    seed_host(caseA, "host-1", agent_online=True)
    seed_host(caseA, "host-2", agent_online=False)
    caseB = seed_case("caseB")
    seed_host(caseB, "host-3", agent_online=True)

    resp = client.get("/api/agents/stats", headers=env["headers"])
    assert resp.status_code == 200, resp.text
    s = resp.json()["data"]
    assert s["total"] == 3
    assert s["online"] == 2
    assert s["offline"] == 1


def test_stats_filter_by_case_id(client, env):
    caseA = seed_case("caseA")
    seed_host(caseA, "host-1", agent_online=True)
    seed_host(caseA, "host-2", agent_online=False)
    caseB = seed_case("caseB")
    seed_host(caseB, "host-3", agent_online=True)

    rA = client.get(f"/api/agents/stats?case_id={caseA}", headers=env["headers"])
    assert rA.status_code == 200, rA.text
    sA = rA.json()["data"]
    assert sA["total"] == 2 and sA["online"] == 1 and sA["offline"] == 1

    rB = client.get(f"/api/agents/stats?case_id={caseB}", headers=env["headers"])
    assert rB.status_code == 200, rB.text
    sB = rB.json()["data"]
    assert sB["total"] == 1 and sB["online"] == 1 and sB["offline"] == 0


def test_filter_nonexistent_case_id_returns_empty(client, env):
    caseA = seed_case("caseA")
    seed_host(caseA, "host-1", agent_online=True)

    resp = client.get("/api/agents?case_id=99999", headers=env["headers"])
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["total"] == 0
    assert data["items"] == []
