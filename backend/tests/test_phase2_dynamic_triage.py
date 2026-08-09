"""阶段二（动态取证任务）测试套件 — 方案 A 轮询通道 + 默认三项 scope.

覆盖范围：
- 平台侧 API：下发（默认/自定义 scope 校验）、列表查询；
- daemon 侧 API：轮询待执行任务（agent token 鉴权 + host 绑定）、回传结果落库；
- 落库正确性：file_hashes / network_connections / process_events 以 source='triage'
  追加写入，不删除既有快照数据（存量保全）；
- 鉴权：token 缺失/无效 → 401，host 绑定不匹配 → 403；
- 采集器：TriageCollector.collect_triage 按 scope 产出三类结构。

DB 隔离：module-scoped 临时 SQLite（系统 temp 目录），init_db() 仅建库一次；
每用例前清空被测表。agent token 通过 AgentModel 注册+生成，复刻真实 daemon 行为。
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
    tmp_dir = tempfile.mkdtemp(prefix="phase2_")
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

    from app.api.triage_tasks import router as triage_router
    app = FastAPI()
    app.include_router(triage_router, prefix="/api")

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


def seed_host(status="imported", hostname="hostTriage") -> int:
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


def register_agent(host_id: int) -> str:
    """复刻真实 daemon：注册 agent → 生成专属 token，返回明文 token。"""
    from app.models.agent_model import AgentModel
    AgentModel.register(host_id, agent_version="1.0", os_type="Windows")
    token_info = AgentModel.generate_token(host_id)
    assert token_info, "agent token 应生成成功"
    return token_info["token"]


# ============================================================================
# 1) 平台侧：下发与列表
# ============================================================================

def test_create_triage_default_scope(client, env):
    host_id = seed_host()
    resp = client.post(f"/api/hosts/{host_id}/triage-tasks", json={}, headers=env["headers"])
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["scope"] == ["file_hashes", "network", "process_subtree"], \
        "默认 scope 应为三项全勾"
    assert isinstance(data["task_id"], int)


def test_create_triage_invalid_scope_falls_back_to_default(client, env):
    host_id = seed_host()
    resp = client.post(
        f"/api/hosts/{host_id}/triage-tasks",
        json={"scope": ["bogus", "file_hashes"]},
        headers=env["headers"],
    )
    assert resp.status_code == 200
    scope = resp.json()["data"]["scope"]
    assert "bogus" not in scope
    assert "file_hashes" in scope
    # 仅剩非法项时回退默认三项
    resp2 = client.post(
        f"/api/hosts/{host_id}/triage-tasks",
        json={"scope": ["bogus"]},
        headers=env["headers"],
    )
    assert resp2.json()["data"]["scope"] == ["file_hashes", "network", "process_subtree"]


def test_list_triage_tasks(client, env):
    host_id = seed_host()
    client.post(f"/api/hosts/{host_id}/triage-tasks", json={}, headers=env["headers"])
    resp = client.get(f"/api/hosts/{host_id}/triage-tasks", headers=env["headers"])
    assert resp.status_code == 200
    rows = resp.json()["data"]
    assert len(rows) == 1
    assert rows[0]["status"] == "pending"
    assert rows[0]["scope"] == ["file_hashes", "network", "process_subtree"]


# ============================================================================
# 2) daemon 侧：轮询 + 回传
# ============================================================================

def test_agent_poll_pending_marks_running(client, env):
    host_id = seed_host()
    token = register_agent(host_id)
    agent_headers = {"Authorization": f"Bearer {token}"}
    client.post(f"/api/hosts/{host_id}/triage-tasks", json={}, headers=env["headers"])

    resp = client.get(
        f"/api/hosts/{host_id}/triage-tasks/pending", headers=agent_headers
    )
    assert resp.status_code == 200
    task = resp.json()["data"]
    assert task is not None
    assert "file_hashes" in task["scope"]
    # get_pending 取任务后将其置为 running（返回体 status 仍为 pending，DB 已变更）
    with get_connection() as conn:
        db_status = conn.execute(
            "SELECT status FROM triage_tasks WHERE id=?", [task["id"]]
        ).fetchone()["status"]
    assert db_status == "running"

    # 再次轮询应无 pending（已被置 running）
    resp2 = client.get(
        f"/api/hosts/{host_id}/triage-tasks/pending", headers=agent_headers
    )
    assert resp2.json()["data"] is None


def test_agent_report_result_appends_triage_source(client, env):
    host_id = seed_host()
    token = register_agent(host_id)
    agent_headers = {"Authorization": f"Bearer {token}"}
    create = client.post(f"/api/hosts/{host_id}/triage-tasks", json={}, headers=env["headers"])
    task_id = create.json()["data"]["task_id"]

    # 既有快照数据（存量，必须保全）
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO file_hashes (host_id, file_path, file_name, sha256, source) "
            "VALUES (?,?,?,?,?)",
            [host_id, "C:/snapshot.exe", "snapshot.exe", "abc", "snapshot"],
        )
        conn.execute(
            "INSERT INTO network_connections (host_id, protocol, remote_addr, source) "
            "VALUES (?,?,?,?)",
            [host_id, "tcp", "1.1.1.1", "snapshot"],
        )

    result = {
        "file_hashes": [{
            "file_path": "C:/live.dll", "file_name": "live.dll", "sha256": "dead",
            "is_signed": True, "signer": "ACME", "file_size": 1234,
            "product_name": "P", "product_version": "1.0", "collected_at": "2026-08-08T00:00:00",
        }],
        "network_connections": [{
            "protocol": "tcp", "local_address": "10.0.0.1", "local_port": 5000,
            "remote_address": "8.8.8.8", "remote_port": 443, "state": "ESTABLISHED",
            "pid": 999, "process_name": "svchost.exe", "collected_at": "2026-08-08T00:00:00",
        }],
        "process_events": [{
            "event_type": "process_start", "pid": 1234, "ppid": 4,
            "process_name": "malware.exe", "process_path": "C:/malware.exe",
            "command_line": "malware.exe -q", "parent_name": "explorer.exe",
            "start_time": "2026-08-08T00:00:00", "event_time": "2026-08-08T00:00:01",
        }],
        "summary": {},
    }
    resp = client.post(
        f"/api/hosts/{host_id}/triage-tasks/{task_id}/result",
        json=result, headers=agent_headers,
    )
    assert resp.status_code == 200, resp.text
    written = resp.json()["data"]["written"]
    assert written == {"file_hashes": 1, "network_connections": 1, "process_events": 1}

    # 落库校验：source='triage' 且存量未被删除
    with get_connection() as conn:
        fh = conn.execute(
            "SELECT * FROM file_hashes WHERE host_id=?", [host_id]
        ).fetchall()
        assert len(fh) == 2, "应追加为 2 条（存量 1 + triage 1），不得覆盖"
        assert any(r["source"] == "triage" for r in fh)
        assert any(r["source"] == "snapshot" for r in fh)

        nc = conn.execute(
            "SELECT * FROM network_connections WHERE host_id=?", [host_id]
        ).fetchall()
        assert len(nc) == 2
        assert any(r["source"] == "triage" for r in nc)

        pe = conn.execute(
            "SELECT * FROM process_events WHERE host_id=?", [host_id]
        ).fetchall()
        assert len(pe) == 1 and pe[0]["source"] == "triage"
        assert pe[0]["event_type"] == "process_start"

    # 任务状态应变为 done 且带汇总
    lst = client.get(f"/api/hosts/{host_id}/triage-tasks", headers=env["headers"]).json()["data"]
    assert lst[0]["status"] == "done"
    assert lst[0]["summary"]["process_events"] == 1


# ============================================================================
# 3) 鉴权
# ============================================================================

def test_agent_endpoints_require_token(client, env):
    host_id = seed_host()
    # 无 token
    r1 = client.get(f"/api/hosts/{host_id}/triage-tasks/pending")
    assert r1.status_code == 401
    # 用户 JWT 不能当 agent token
    r2 = client.get(
        f"/api/hosts/{host_id}/triage-tasks/pending", headers=env["headers"]
    )
    assert r2.status_code == 401


def test_agent_host_binding_mismatch(client, env):
    host_a = seed_host(hostname="hostA")
    host_b = seed_host(hostname="hostB")
    token = register_agent(host_a)  # token 仅绑定 host_a
    agent_headers = {"Authorization": f"Bearer {token}"}
    # 用同一 token 访问 host_b 应 403
    r = client.get(f"/api/hosts/{host_b}/triage-tasks/pending", headers=agent_headers)
    assert r.status_code == 403


# ============================================================================
# 4) 采集器：按 scope 产出三类结构
# ============================================================================

class _FakeFiles:
    def collect(self):
        return {"file_hashes": [{"file_path": "x", "sha256": "y"}]}


class _FakeNetwork:
    def collect(self):
        return [{"protocol": "tcp", "local_address": "1.1.1.1",
                 "remote_address": "2.2.2.2", "pid": 1,
                 "process_name": "p", "collected_at": "t"}]


class _FakeProcesses:
    def collect(self):
        return [{"pid": 1, "ppid": 0, "name": "p", "path": "pa",
                 "command_line": "c", "parent_name": "pp",
                 "create_time": "2026-08-08T00:00:00"}]


def test_triage_collector_scope_shapes(monkeypatch):
    import collectors.files as files_mod
    import collectors.network as net_mod
    import collectors.processes as proc_mod
    monkeypatch.setattr(files_mod, "FilesCollector", _FakeFiles)
    monkeypatch.setattr(net_mod, "NetworkCollector", _FakeNetwork)
    monkeypatch.setattr(proc_mod, "ProcessesCollector", _FakeProcesses)

    from collectors.triage import TriageCollector
    result = TriageCollector.collect_triage(["file_hashes", "network", "process_subtree"])
    assert len(result["file_hashes"]) == 1
    assert len(result["network_connections"]) == 1
    assert len(result["process_events"]) == 1
    # process 映射为 process_start 事件
    pe = result["process_events"][0]
    assert pe["event_type"] == "process_start"
    assert pe["pid"] == 1 and pe["process_name"] == "p"
    # network 映射字段对齐 network_connections 表
    nc = result["network_connections"][0]
    assert nc["local_address"] == "1.1.1.1" and nc["remote_address"] == "2.2.2.2"


def test_triage_collector_partial_scope(monkeypatch):
    import collectors.files as files_mod
    monkeypatch.setattr(files_mod, "FilesCollector", _FakeFiles)
    from collectors.triage import TriageCollector
    result = TriageCollector.collect_triage(["file_hashes"])
    assert len(result["file_hashes"]) == 1
    assert result["network_connections"] == []
    assert result["process_events"] == []


def test_triage_collector_degrades_on_error(monkeypatch):
    """采集器异常时降级为空列表，绝不抛异常拖垮 daemon。"""

    class _Boom:
        def collect(self):
            raise RuntimeError("boom")

    import collectors.files as files_mod
    monkeypatch.setattr(files_mod, "FilesCollector", _Boom)
    from collectors.triage import TriageCollector
    result = TriageCollector.collect_triage(["file_hashes"])
    assert result["file_hashes"] == []
