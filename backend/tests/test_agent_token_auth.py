"""QA — 主机 Agent 专属 Token 认证机制 测试套件（T11 QA 阶段）.

负责人：严过关（Yan）· QA 工程师
日期：2026-08-07
关联设计：deliverables/software-company/agent-token-fix/design.md §8（测试要点）
关联实现：deliverables/software-company/agent-token-fix/implementation.md

覆盖范围：
- 接口层（FastAPI TestClient）：生成/重置 token、bootstrap、heartbeat、disconnect、
  process-events 的鉴权与 host_id 绑定（401/403/404）、列表/stats 惰性折算、token 明文保密。
- 模型层（AgentModel）：generate_token / get_by_token_hash / get_token_status、
  64 hex hash、唯一索引。
- 兼容层：存量 agents 行 token_hash=NULL 升级启动不报错、旧 agent 无 token 连新后端 401。

DB 隔离（重要）：
- module-scoped 临时 SQLite（系统 temp 目录，绝不落在 backend/data 下），
  settings.DB_PATH 指向它，init_db() 仅建库一次；每用例前清空被测表（agents/hosts/cases/
  audit_logs/process_events），保证用例间数据隔离且不污染 backend/data/ir_platform.db。
- DB_JOURNAL_MODE 置 DELETE，规避 Windows WAL 文件锁；module 结束恢复原 DB_PATH。
"""

import os
import re
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

# ── 路径准备：backend 根目录入 sys.path（与 conftest.py 一致） ──
_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import init_db, get_connection  # noqa: E402


# ============================================================================
# fixture：module-scoped 隔离库 + 共享 app/TestClient + 每用例清表
# ============================================================================

_TABLES_TO_CLEAR = ["process_events", "audit_logs", "agents", "hosts", "cases"]


def _clear_data() -> None:
    """清空被测业务表，保证用例间隔离（不删 schema）。"""
    with get_connection() as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        for t in _TABLES_TO_CLEAR:
            conn.execute(f"DELETE FROM {t}")
        conn.execute("PRAGMA foreign_keys = ON")


@pytest.fixture(scope="module")
def qa_env():
    """module-scoped 隔离环境：临时库 + admin JWT + 共享最小 app/TestClient。

    - 临时库放系统 temp 目录（tempfile.mkdtemp），绝不触碰 backend/data/ir_platform.db；
    - init_db() 只执行一次（全量建库成本高），之后每用例靠 _clear_data 隔离；
    - module 结束时恢复原 DB_PATH / DB_JOURNAL_MODE 并清理临时目录。
    """
    original = settings.DB_PATH
    original_jm = getattr(settings, "DB_JOURNAL_MODE", "WAL")

    tmp_dir = tempfile.mkdtemp(prefix="qa_agent_token_")
    db_path = str(Path(tmp_dir) / "test.db")
    settings.DB_PATH = db_path
    settings.DB_JOURNAL_MODE = "DELETE"
    init_db()

    from app.models.user import User
    from app.services.auth_service import create_token
    user = User.get_by_username("admin")
    assert user is not None, "init_db 后应存在默认 admin 用户"
    jwt = create_token(user)
    headers = {"Authorization": f"Bearer {jwt}"}

    # 最小 app：仅挂载被测路由
    from app.api.agents import router as agents_router
    from app.api.process_events import router as pe_router

    app = FastAPI()
    app.include_router(agents_router, prefix="/api")
    app.include_router(pe_router, prefix="/api")

    ctx = {
        "db_path": db_path,
        "tmp_dir": tmp_dir,
        "jwt": jwt,
        "headers": headers,
        "user": user,
        "app": app,
    }
    yield ctx

    # module teardown
    settings.DB_PATH = original
    settings.DB_JOURNAL_MODE = original_jm
    shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.fixture()
def client(qa_env):
    """每用例独立 TestClient；用例结束自动关闭，避免连接/句柄泄漏。"""
    with TestClient(qa_env["app"]) as c:
        _clear_data()  # 用例开始时清空数据，保证隔离
        yield c


# ============================================================================
# 数据准备辅助
# ============================================================================

def seed_case(conn, name="QA 案件", number=None) -> int:
    cur = conn.execute(
        "INSERT INTO cases (name, case_number) VALUES (?, ?)",
        [name, number or f"QA-{uuid.uuid4().hex[:8]}"],
    )
    return int(cur.lastrowid)


def seed_host(hostname="hostA", ip="10.0.0.1", os_type="windows") -> int:
    """插入 case + host，返回 host_id。"""
    with get_connection() as conn:
        cid = seed_case(conn)
        cur = conn.execute(
            "INSERT INTO hosts (case_id, hostname, ip_address, os_type) VALUES (?, ?, ?, ?)",
            [cid, hostname, ip, os_type],
        )
        return int(cur.lastrowid)


def seed_agent_row(host_id, token_hash=None, last_heartbeat=None, status="offline") -> None:
    """直接向 agents 表插入一行（模拟存量/预置数据）。"""
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO agents (host_id, agent_id, status, last_heartbeat, token_hash)
               VALUES (?, ?, ?, ?, ?)""",
            [host_id, f"agent-{uuid.uuid4().hex[:12]}", status, last_heartbeat, token_hash],
        )


def gen_token(client, host_id, headers=None):
    """通过接口生成 token，返回响应。"""
    hdrs = headers or _DEFAULT_HEADERS
    return client.post(f"/api/agents/{host_id}/token", headers=hdrs)


_DEFAULT_HEADERS = None  # 由 client fixture 写入


# ============================================================================
# 正常路径
# ============================================================================

class TestNormalPath:
    """TC-01 ~ TC-05：生成 token → 心跳/上报 200；仅 token 自举拿 host_id。"""

    def test_tc01_generate_token_ok(self, client, qa_env):
        hid = seed_host()
        resp = gen_token(client, hid, qa_env["headers"])
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["code"] == 0
        data = body["data"]
        assert data["host_id"] == hid
        assert data["agent_id"].startswith("agent-")
        assert data["token"].startswith("atk_")
        assert len(data["token"]) > 32
        assert data["token_set"] is True
        assert data["token_created_at"]  # 非空

    def test_tc02_heartbeat_with_token_200(self, client, qa_env):
        hid = seed_host()
        token = gen_token(client, hid, qa_env["headers"]).json()["data"]["token"]
        resp = client.post(
            f"/api/hosts/{hid}/heartbeat",
            headers={"Authorization": f"Bearer {token}"},
            json={"agent_id": f"agent-{hid}"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success"] is True
        assert body["status"] == "ok"
        # 心跳后应写 status=online + last_heartbeat
        with get_connection() as conn:
            row = conn.execute(
                "SELECT status, last_heartbeat FROM agents WHERE host_id=?", [hid]
            ).fetchone()
            assert row["status"] == "online"
            assert row["last_heartbeat"]

    def test_tc03_process_events_with_token_200(self, client, qa_env):
        hid = seed_host()
        token = gen_token(client, hid, qa_env["headers"]).json()["data"]["token"]
        resp = client.post(
            f"/api/hosts/{hid}/process-events",
            headers={"Authorization": f"Bearer {token}"},
            json=[{"event_type": "process_start", "pid": 100, "process_name": "notepad.exe"}],
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "written" in body and "alerts" in body
        assert body["written"] == 1

    def test_tc04_bootstrap_only_token(self, client, qa_env):
        """仅 token（不带 --daemon-id）自举：拿回 host_id + 刷新元数据。"""
        hid = seed_host(hostname="OLD-HOST", ip="10.0.0.1", os_type="windows")
        token = gen_token(client, hid, qa_env["headers"]).json()["data"]["token"]
        resp = client.post(
            "/api/agents/bootstrap",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "hostname": "NEW-HOST",
                "ip_address": "10.9.9.9",
                "os_type": "linux",
                "agent_version": "2.0.0",
                "collectors": ["process_events"],
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["host_id"] == hid
        assert data["token_valid"] is True
        # 元数据应被刷新到 hosts 与 agents
        with get_connection() as conn:
            h = conn.execute("SELECT * FROM hosts WHERE id=?", [hid]).fetchone()
            assert h["hostname"] == "NEW-HOST"
            assert h["ip_address"] == "10.9.9.9"
            assert h["os_type"] == "linux"
            a = conn.execute("SELECT * FROM agents WHERE host_id=?", [hid]).fetchone()
            assert a["agent_version"] == "2.0.0"
            assert a["status"] == "online"
            assert a["last_heartbeat"]

    def test_tc05_disconnect_ok(self, client, qa_env):
        hid = seed_host()
        token = gen_token(client, hid, qa_env["headers"]).json()["data"]["token"]
        resp = client.post(
            f"/api/hosts/{hid}/disconnect",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["success"] is True
        with get_connection() as conn:
            row = conn.execute("SELECT status FROM agents WHERE host_id=?", [hid]).fetchone()
            assert row["status"] == "offline"


# ============================================================================
# 异常 / 边界
# ============================================================================

class TestEdgeCases:
    """TC-06 ~ TC-11：缺 token / 无效 token / 重置 / host 绑定 / 无 Bearer / 404。"""

    def test_tc06_generate_token_host_not_found_404(self, client, qa_env):
        resp = gen_token(client, 999999, qa_env["headers"])
        assert resp.status_code == 404, resp.text
        assert "不存在" in resp.json()["detail"]

    def test_tc07_generate_token_auto_insert_agents_row(self, client, qa_env):
        """host 存在但 agents 无行 → 自动补齐一行再写 token。"""
        hid = seed_host()
        with get_connection() as conn:
            cnt = conn.execute("SELECT COUNT(*) c FROM agents WHERE host_id=?", [hid]).fetchone()["c"]
            assert cnt == 0
        resp = gen_token(client, hid, qa_env["headers"])
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["agent_id"].startswith("agent-")
        with get_connection() as conn:
            row = conn.execute("SELECT token_hash FROM agents WHERE host_id=?", [hid]).fetchone()
            assert row and row["token_hash"]

    def test_tc08_invalid_token_401(self, client, qa_env):
        """无效 token（如 123）打心跳/上报 → 401，平台不写心跳。"""
        hid = seed_host()
        resp = client.post(
            f"/api/hosts/{hid}/heartbeat",
            headers={"Authorization": "Bearer 123"},
            json={},
        )
        assert resp.status_code == 401, resp.text
        assert "Invalid agent token" in resp.json()["detail"]
        resp2 = client.post(
            f"/api/hosts/{hid}/process-events",
            headers={"Authorization": "Bearer atk_not_exist"},
            json=[{"event_type": "process_start", "pid": 1}],
        )
        assert resp2.status_code == 401, resp2.text

    def test_tc09_reset_invalidates_old_token(self, client, qa_env):
        """重置后旧 token 立即失效，新 token 可用。"""
        hid = seed_host()
        old = gen_token(client, hid, qa_env["headers"]).json()["data"]["token"]
        assert client.post(
            f"/api/hosts/{hid}/heartbeat", headers={"Authorization": f"Bearer {old}"}, json={}
        ).status_code == 200
        # 重置（再次 POST）
        new = gen_token(client, hid, qa_env["headers"]).json()["data"]["token"]
        assert new != old
        # 旧 token 立即失效 → 401
        resp_old = client.post(
            f"/api/hosts/{hid}/heartbeat", headers={"Authorization": f"Bearer {old}"}, json={}
        )
        assert resp_old.status_code == 401, resp_old.text
        # 新 token 可用
        assert client.post(
            f"/api/hosts/{hid}/heartbeat", headers={"Authorization": f"Bearer {new}"}, json={}
        ).status_code == 200

    def test_tc10_host_binding_mismatch_403(self, client, qa_env):
        """A 主机 token 打 B 主机心跳/上报 → 403，B 状态不被污染。"""
        hid_a = seed_host("hostA")
        hid_b = seed_host("hostB")
        token_a = gen_token(client, hid_a, qa_env["headers"]).json()["data"]["token"]
        # 心跳 403
        resp = client.post(
            f"/api/hosts/{hid_b}/heartbeat",
            headers={"Authorization": f"Bearer {token_a}"},
            json={},
        )
        assert resp.status_code == 403, resp.text
        assert "不匹配" in resp.json()["detail"]
        # B 心跳未被写
        with get_connection() as conn:
            row = conn.execute("SELECT last_heartbeat FROM agents WHERE host_id=?", [hid_b]).fetchone()
            assert row is None or not row["last_heartbeat"]
        # 上报 403
        resp2 = client.post(
            f"/api/hosts/{hid_b}/process-events",
            headers={"Authorization": f"Bearer {token_a}"},
            json=[{"event_type": "process_start", "pid": 2}],
        )
        assert resp2.status_code == 403, resp2.text

    def test_tc11_no_bearer_401(self, client, qa_env):
        """无 Bearer 头直接打 heartbeat / process-events → 401（原零鉴权漏洞封堵）。"""
        hid = seed_host()
        resp = client.post(f"/api/hosts/{hid}/heartbeat", json={})
        assert resp.status_code == 401, resp.text
        resp2 = client.post(
            f"/api/hosts/{hid}/process-events", json=[{"event_type": "process_start", "pid": 3}]
        )
        assert resp2.status_code == 401, resp2.text


# ============================================================================
# 安全
# ============================================================================

class TestSecurity:
    """TC-12 ~ TC-15：token 明文保密、重置吊销、跨 host 伪造、日志无明文。"""

    def test_tc12_token_plaintext_only_once_in_response(self, client, qa_env):
        """token 明文只在生成接口响应中出现一次，列表/DB 不含明文。"""
        hid = seed_host()
        token = gen_token(client, hid, qa_env["headers"]).json()["data"]["token"]
        assert token.startswith("atk_")
        # DB 中只存 hash，不存明文
        with get_connection() as conn:
            row = conn.execute(
                "SELECT token_hash, token_created_at FROM agents WHERE host_id=?", [hid]
            ).fetchone()
            assert row["token_hash"] != token
            assert len(row["token_hash"]) == 64
        # 列表接口不含明文 token 也不含 token_hash 字段
        resp = client.get("/api/agents", headers=qa_env["headers"])
        assert resp.status_code == 200, resp.text
        items = resp.json()["data"]["items"]
        assert len(items) == 1
        item = items[0]
        assert "token" not in item
        assert "token_hash" not in item
        assert item["token_set"] is True
        assert item["token_created_at"]
        # 序列化后也不应包含明文
        assert token not in resp.text

    def test_tc13_reset_revokes_old_token(self, client, qa_env):
        """token 泄露处置：重置后旧 token 无法再上报（bootstrap 与上报均 401）。"""
        hid = seed_host()
        old = gen_token(client, hid, qa_env["headers"]).json()["data"]["token"]
        gen_token(client, hid, qa_env["headers"])  # 重置
        assert client.post(
            "/api/agents/bootstrap", headers={"Authorization": f"Bearer {old}"}, json={}
        ).status_code == 401
        assert client.post(
            f"/api/hosts/{hid}/process-events",
            headers={"Authorization": f"Bearer {old}"},
            json=[{"event_type": "process_start", "pid": 9}],
        ).status_code == 401

    def test_tc14_cross_host_forge_403(self, client, qa_env):
        """跨 host 伪造：伪造 token 归属 host 与路径 host 不同 → 403。"""
        hid_a = seed_host("hostA")
        hid_b = seed_host("hostB")
        token_a = gen_token(client, hid_a, qa_env["headers"]).json()["data"]["token"]
        assert client.post(
            f"/api/hosts/{hid_b}/heartbeat",
            headers={"Authorization": f"Bearer {token_a}"},
            json={},
        ).status_code == 403
        assert client.post(
            f"/api/hosts/{hid_b}/process-events",
            headers={"Authorization": f"Bearer {token_a}"},
            json=[{"event_type": "process_start", "pid": 4}],
        ).status_code == 403
        assert client.post(
            f"/api/hosts/{hid_b}/disconnect",
            headers={"Authorization": f"Bearer {token_a}"},
        ).status_code == 403

    def test_tc15_no_token_plaintext_in_audit_log(self, client, qa_env):
        """审计日志 detail 不含 token 明文（仅 host_id/agent_id）。"""
        hid = seed_host()
        token = gen_token(client, hid, qa_env["headers"]).json()["data"]["token"]
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT detail FROM audit_logs WHERE action_type='agent_token_generate'"
            ).fetchall()
            assert rows, "应写入 audit_logs"
            joined = "\n".join(r["detail"] for r in rows)
            assert token not in joined
            assert f"host_id={hid}" in joined


# ============================================================================
# 兼容性
# ============================================================================

class TestCompatibility:
    """TC-16 ~ TC-17：存量 agents token_hash=NULL 升级、旧 agent 连新后端 401。"""

    def test_tc16_legacy_null_token_ok(self, client, qa_env):
        """存量 agents 行 token_hash=NULL 升级启动不报错，列表 token_set=false。"""
        hid = seed_host()
        seed_agent_row(hid, token_hash=None, status="offline")
        # 再跑一次 init_db 模拟升级重启，不抛异常
        init_db()
        resp = client.get("/api/agents", headers=qa_env["headers"])
        assert resp.status_code == 200, resp.text
        items = resp.json()["data"]["items"]
        assert len(items) == 1
        item = items[0]
        assert item["token_set"] is False
        assert item["token_created_at"] is None
        assert "token_hash" not in item

    def test_tc17_legacy_agent_no_token_401_no_500(self, client, qa_env):
        """旧 agent（无 token）连新后端 → 401，且不是 500 异常堆栈。"""
        hid = seed_host()
        seed_agent_row(hid, token_hash=None)
        # 无 Authorization 头 → 401
        resp = client.post(f"/api/hosts/{hid}/heartbeat", json={})
        assert resp.status_code == 401, resp.text
        assert "Invalid agent token" in resp.json()["detail"]
        # 伪 token → 401
        resp2 = client.post(
            f"/api/hosts/{hid}/process-events",
            headers={"Authorization": "Bearer fake"},
            json=[{"event_type": "process_start", "pid": 5}],
        )
        assert resp2.status_code == 401, resp2.text


# ============================================================================
# 列表 / 统计惰性折算
# ============================================================================

class TestLazyOnline:
    """TC-18 ~ TC-20：90s 窗口惰性折算在线状态。"""

    def test_tc18_list_lazy_online_offline(self, client, qa_env):
        hid_online = seed_host("onlineHost")
        hid_offline = seed_host("offlineHost")
        # 直接构造 last_heartbeat：一个 10s 内，一个 300s 前
        seed_agent_row(hid_online, last_heartbeat="__NOW__", status="offline")
        seed_agent_row(hid_offline, last_heartbeat=None, status="offline")
        with get_connection() as conn:
            conn.execute(
                "UPDATE agents SET last_heartbeat=datetime('now','-10 seconds') WHERE host_id=?",
                [hid_online],
            )
            conn.execute(
                "UPDATE agents SET last_heartbeat=datetime('now','-300 seconds') WHERE host_id=?",
                [hid_offline],
            )
        resp = client.get("/api/agents", headers=qa_env["headers"])
        assert resp.status_code == 200, resp.text
        by_host = {it["host_id"]: it["status"] for it in resp.json()["data"]["items"]}
        assert by_host[hid_online] == "online", by_host
        assert by_host[hid_offline] == "offline", by_host

    def test_tc19_stats_lazy_online_offline(self, client, qa_env):
        hid_online = seed_host("onlineHost")
        hid_offline = seed_host("offlineHost")
        seed_agent_row(hid_online)
        seed_agent_row(hid_offline)
        with get_connection() as conn:
            conn.execute(
                "UPDATE agents SET last_heartbeat=datetime('now','-10 seconds') WHERE host_id=?",
                [hid_online],
            )
            conn.execute(
                "UPDATE agents SET last_heartbeat=datetime('now','-300 seconds') WHERE host_id=?",
                [hid_offline],
            )
        resp = client.get("/api/agents/stats", headers=qa_env["headers"])
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["total"] == 2
        assert data["online"] == 1
        assert data["offline"] == 1

    def test_tc20_disconnect_sets_offline_in_list(self, client, qa_env):
        """disconnect 后列表状态应折算为 offline（配合 disconnect 写 status=offline）。"""
        hid = seed_host()
        token = gen_token(client, hid, qa_env["headers"]).json()["data"]["token"]
        client.post(f"/api/hosts/{hid}/heartbeat", headers={"Authorization": f"Bearer {token}"}, json={})
        with get_connection() as conn:
            conn.execute(
                "UPDATE agents SET last_heartbeat=datetime('now','-300 seconds') WHERE host_id=?",
                [hid],
            )
        resp = client.get("/api/agents", headers=qa_env["headers"])
        items = {it["host_id"]: it["status"] for it in resp.json()["data"]["items"]}
        assert items[hid] == "offline"


# ============================================================================
# 模型层单测
# ============================================================================

class TestModelLayer:
    """TC-21 ~ TC-25：generate_token / get_by_token_hash / get_token_status / 唯一索引 / 64hex。"""

    def test_tc21_model_generate_token_hash_64hex(self, client, qa_env):
        from app.models.agent_model import AgentModel
        hid = seed_host()
        seed_agent_row(hid)
        result = AgentModel.generate_token(hid)
        assert result is not None
        assert result["token"].startswith("atk_")
        assert re.fullmatch(r"[0-9a-f]{64}", result["token_hash"])
        assert result["host_id"] == hid
        assert result["agent_id"]
        # DB 落库确认
        with get_connection() as conn:
            row = conn.execute(
                "SELECT token_hash, token_created_at FROM agents WHERE host_id=?", [hid]
            ).fetchone()
            assert row["token_hash"] == result["token_hash"]
            assert row["token_created_at"]

    def test_tc22_model_get_by_token_hash(self, client, qa_env):
        from app.models.agent_model import AgentModel
        hid = seed_host()
        seed_agent_row(hid)
        result = AgentModel.generate_token(hid)
        hit = AgentModel.get_by_token_hash(result["token_hash"])
        assert hit is not None
        assert hit["host_id"] == hid
        assert hit["agent_id"] == result["agent_id"]
        assert AgentModel.get_by_token_hash("f" * 64) is None

    def test_tc23_model_get_token_status(self, client, qa_env):
        from app.models.agent_model import AgentModel
        # 无 agents 行 → token_set=False
        no_row_hid = seed_host("noAgentHost")
        status0 = AgentModel.get_token_status(no_row_hid)
        assert status0["token_set"] is False
        # 有行无 token → False
        hid = seed_host()
        seed_agent_row(hid)
        status1 = AgentModel.get_token_status(hid)
        assert status1["token_set"] is False
        assert status1["token_created_at"] is None
        # 生成后 → True
        AgentModel.generate_token(hid)
        status2 = AgentModel.get_token_status(hid)
        assert status2["token_set"] is True
        assert status2["token_created_at"]

    def test_tc24_model_unique_index(self, client, qa_env):
        """唯一索引：重复 token_hash → IntegrityError；多行 NULL 共存正常。"""
        hid_a = seed_host("hostA")
        hid_b = seed_host("hostB")
        seed_agent_row(hid_a)
        seed_agent_row(hid_b)
        # 多行 NULL 可共存（默认已 NULL）
        with get_connection() as conn:
            conn.execute("UPDATE agents SET token_hash=NULL WHERE host_id IN (?, ?)", [hid_a, hid_b])
        # 尝试写入相同 token_hash 到两个不同 host → 第二个必须抛 IntegrityError
        with pytest.raises(Exception) as exc_info:
            with get_connection() as conn:
                conn.execute("UPDATE agents SET token_hash='A'*64 WHERE host_id=?", [hid_a])
                conn.execute("UPDATE agents SET token_hash='A'*64 WHERE host_id=?", [hid_b])
        assert "UNIQUE" in str(exc_info.value).upper()

    def test_tc25_model_generate_token_without_agents_row(self, client, qa_env):
        """agents 行缺失时 generate_token 返回 None（不伪造）。"""
        from app.models.agent_model import AgentModel
        hid = seed_host("noAgentRowHost")
        assert AgentModel.generate_token(hid) is None


# ============================================================================
# 路由注册 / 生成接口 JWT 鉴权
# ============================================================================

class TestRouteAuth:
    """TC-26 ~ TC-27：生成 token / 列表接口必须有用户 JWT；路由已注册。"""

    def test_tc26_user_endpoints_require_jwt(self, client, qa_env):
        hid = seed_host()
        # 无 JWT → 401
        assert client.post(f"/api/agents/{hid}/token").status_code == 401
        assert client.get("/api/agents").status_code == 401
        assert client.get("/api/agents/stats").status_code == 401
        # 有 JWT → 200
        assert client.get("/api/agents", headers=qa_env["headers"]).status_code == 200
        assert client.get("/api/agents/stats", headers=qa_env["headers"]).status_code == 200

    def test_tc27_routes_registered(self, client):
        # 注意：app.routes 含 WebSocket/Static 等无 methods 属性的路由，需过滤
        routes = {
            getattr(r, "path", None): sorted(getattr(r, "methods", None) or [])
            for r in client.app.routes
            if getattr(r, "path", None) and getattr(r, "methods", None)
        }
        assert "/api/agents/{host_id}/token" in routes
        assert "/api/agents/bootstrap" in routes
        assert "/api/hosts/{host_id}/heartbeat" in routes
        assert "/api/hosts/{host_id}/disconnect" in routes
        assert "/api/hosts/{host_id}/process-events" in routes
