"""P2 测试：长期记忆 API（T4）.

依据：
- ``p2-design.md`` §5（API 接口定义）/ §8 验收 E；
- ``p2-dev.md`` §2.5（4 端点 + 统一信封 + 鉴权）/ §4 偏差 3（错误信封为 {detail:...}
  而非 {code,data,message}）。

覆盖：
- GET /api/memories：列表 + 筛选（event_id/host_id/agent_name/memory_type/q）+ 分页；
- GET /api/memories/search：q 必填（缺 q → FastAPI 422；空白 q → 400 {"detail":"q 不能为空"}）、
  命中、无命中空数组；
- POST /api/memories：content 必填（空 → 400）、非法 memory_type → 400、成功创建
  （created_by=当前用户、tags JSON）；
- DELETE /api/memories/{id}：成功 {deleted:true}；不存在 404 {"detail":"记忆不存在"}；
- 错误信封为 {detail:...}（HTTPException 模式）；未登录访问被鉴权拦截（401）。

环境说明（Windows + Python3.14 已知问题）：每用例新建临时 WAL 库文件会偶发进程级
原生崩溃（与 test_dag_validation 既有崩溃同源，非 P2 引入）。本文件改用
**module-scoped** 临时库（整个文件仅 1 次 init_db），每用例清空 ``agent_memories``，
规避该环境崩溃。

约束：DB 走隔离临时 SQLite；鉴权用 dependency_overrides 注入 admin（与
test_preset_use_endpoint.py 同模式）；401 用例不注入 override。
"""

import json
import os
import sys
import uuid
from pathlib import Path

_THIS = Path(__file__).resolve().parent
_BACKEND = _THIS.parent
for _p in (str(_BACKEND), str(_THIS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.config as config
from app.api.memories import router as memories_router
from app.models.agent_memory import AgentMemory
from app.services.auth_service import get_current_user

_USER = {"id": 1, "username": "admin", "role": "admin"}


def _init_db_at(path: str) -> None:
    config.settings.DB_PATH = path
    Path(config.settings.DATA_DIR).mkdir(parents=True, exist_ok=True)
    from app.database import init_db
    init_db()


@pytest.fixture(scope="module")
def api_db():
    """module-scoped 临时 SQLite（整个文件仅 1 次 init_db，规避多库崩溃）。"""
    original = config.settings.DB_PATH
    data_dir = _BACKEND / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    path = str(data_dir / f"test_p2_api_{uuid.uuid4().hex[:8]}.db")
    _init_db_at(path)
    yield path
    config.settings.DB_PATH = original
    for suffix in ("", "-wal", "-shm"):
        p = path + suffix
        if os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass


@pytest.fixture()
def clear_mem(api_db):
    """每用例清空 agent_memories（保持计数断言语义）。"""
    from app.database import get_connection
    with get_connection() as conn:
        conn.execute("DELETE FROM agent_memories")
    return api_db


@pytest.fixture()
def client(clear_mem):
    """已登录 TestClient（dependency_overrides 注入 admin）。"""
    app = FastAPI()
    app.include_router(memories_router, prefix="/api/memories")
    app.dependency_overrides[get_current_user] = lambda: _USER
    return TestClient(app)


@pytest.fixture()
def client_no_auth(clear_mem):
    """未登录 TestClient（不注入 override → 401）。"""
    app = FastAPI()
    app.include_router(memories_router, prefix="/api/memories")
    return TestClient(app)


class TestListEndpoint:
    def test_list_empty(self, client):
        resp = client.get("/api/memories")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["code"] == 0
        assert body["data"] == {"items": [], "total": 0, "page": 1, "page_size": 50}

    def test_list_filters_and_pagination(self, client):
        AgentMemory.create(event_id="evt-a", host_id=1, agent_name="root_cause",
                           memory_type="conclusion", content="事件A 根因结论", tags=["powershell"])
        AgentMemory.create(event_id="evt-a", host_id=1, agent_name="responder",
                           memory_type="disposition", content="事件A 处置记录", tags=["隔离"])
        AgentMemory.create(event_id="evt-b", host_id=2, agent_name="reporter",
                           memory_type="summary", content="事件B 报告摘要", tags=[])

        # 全部
        resp = client.get("/api/memories")
        assert resp.json()["data"]["total"] == 3
        # 按 event 筛选
        resp = client.get("/api/memories", params={"event_id": "evt-a"})
        assert resp.json()["data"]["total"] == 2
        # 按 host 筛选
        resp = client.get("/api/memories", params={"host_id": 2})
        assert resp.json()["data"]["total"] == 1
        # 按 agent 筛选
        resp = client.get("/api/memories", params={"agent_name": "responder"})
        assert resp.json()["data"]["total"] == 1
        # 按 type 筛选
        resp = client.get("/api/memories", params={"memory_type": "conclusion"})
        assert resp.json()["data"]["total"] == 1
        # q 关键词
        resp = client.get("/api/memories", params={"q": "根因"})
        assert resp.json()["data"]["total"] == 1
        # 分页
        resp = client.get("/api/memories", params={"page": 1, "page_size": 2})
        data = resp.json()["data"]
        assert data["total"] == 3
        assert len(data["items"]) == 2
        assert data["page_size"] == 2

    def test_list_unauthorized_401(self, client_no_auth):
        resp = client_no_auth.get("/api/memories")
        assert resp.status_code == 401, resp.text


class TestSearchEndpoint:
    def test_search_missing_q_422(self, client):
        """缺 q → FastAPI 参数校验 422（dev 偏差：q 必填由 Query(min_length=1) 保证）。"""
        resp = client.get("/api/memories/search")
        assert resp.status_code == 422, resp.text

    def test_search_blank_q_400(self, client):
        """q 空白 → 400 {"detail": "q 不能为空"}。"""
        resp = client.get("/api/memories/search", params={"q": "   "})
        assert resp.status_code == 400, resp.text
        assert resp.json() == {"detail": "q 不能为空"}

    def test_search_hit_and_miss(self, client):
        AgentMemory.create(content="攻击者通过 powershell 拉起 rundll32", tags=["C2"],
                           event_id="evt-a", host_id=1)
        resp = client.get("/api/memories/search", params={"q": "powershell"})
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total"] == 1
        assert data["items"][0]["content"] == "攻击者通过 powershell 拉起 rundll32"
        # 无命中 → 空数组
        resp2 = client.get("/api/memories/search", params={"q": "不存在关键词"})
        assert resp2.status_code == 200
        assert resp2.json()["data"] == {"items": [], "total": 0}

    def test_search_filters(self, client):
        AgentMemory.create(content="A 内容", tags=[], event_id="evt-a", host_id=1)
        AgentMemory.create(content="B 内容", tags=[], event_id="evt-b", host_id=2)
        resp = client.get("/api/memories/search", params={"q": "内容", "host_id": 2})
        assert resp.json()["data"]["total"] == 1
        assert resp.json()["data"]["items"][0]["event_id"] == "evt-b"


class TestCreateEndpoint:
    def test_create_missing_content_400(self, client):
        resp = client.post("/api/memories", json={})
        assert resp.status_code == 400, resp.text
        assert resp.json() == {"detail": "content 不能为空"}
        # 空白 content 同样 400
        resp2 = client.post("/api/memories", json={"content": "   "})
        assert resp2.status_code == 400

    def test_create_invalid_memory_type_400(self, client):
        resp = client.post("/api/memories", json={"content": "内容", "memory_type": "bad"})
        assert resp.status_code == 400, resp.text
        assert resp.json() == {"detail": "非法 memory_type: bad"}

    def test_create_success_created_by_current_user(self, client):
        resp = client.post(
            "/api/memories",
            json={"content": "手动写入的记忆", "memory_type": "conclusion",
                  "event_id": "evt-x", "host_id": 5, "agent_name": "manual",
                  "source_node": "manual", "tags": ["tag1", "tag2"]},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["code"] == 0
        data = body["data"]
        assert data["id"] > 0
        assert data["content"] == "手动写入的记忆"
        assert data["memory_type"] == "conclusion"
        assert data["created_by"] == "admin"          # 当前登录用户（dependency_overrides）
        assert json.loads(data["tags"]) == ["tag1", "tag2"]
        assert data["created_at"]

    def test_create_default_type_summary(self, client):
        resp = client.post("/api/memories", json={"content": "无类型"})
        assert resp.status_code == 200
        assert resp.json()["data"]["memory_type"] == "summary"


class TestDeleteEndpoint:
    def test_delete_success(self, client):
        row = AgentMemory.create(content="待删除")
        resp = client.delete(f"/api/memories/{row['id']}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["code"] == 0
        assert body["data"] == {"deleted": True}
        assert AgentMemory.get_by_id(row["id"]) is None

    def test_delete_missing_404(self, client):
        resp = client.delete("/api/memories/999999")
        assert resp.status_code == 404, resp.text
        assert resp.json() == {"detail": "记忆不存在"}

    def test_all_endpoints_unauthorized_401(self, client_no_auth):
        """未登录访问 4 端点均 401（验收 E 第 2 条）。"""
        assert client_no_auth.get("/api/memories").status_code == 401
        assert client_no_auth.get("/api/memories/search", params={"q": "x"}).status_code == 401
        assert client_no_auth.post("/api/memories", json={"content": "x"}).status_code == 401
        assert client_no_auth.delete("/api/memories/1").status_code == 401


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-v"]))
