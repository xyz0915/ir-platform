"""Test: POST /api/agent-management/pipeline/presets/{preset_id}/use 端点.

覆盖 commit 97028159 新增的使用热度统计端点：
  - 创建带元数据预设后调用 /use → code=0，usage_count +1，last_used_at 非空
  - 重复调用累加
  - 不存在的 preset_id → 404
  - create_preset 读取 category/tags，author 取当前登录用户名
  - list 接口 tags 解析为数组

DB 走隔离临时 SQLite（绝不触碰 backend/data 下的真实库）。
鉴权用 dependency_overrides 注入 admin 用户，避免真实 token（与 test_agent_api_e2e 同模式）。
"""

import os
import sys
import tempfile
from pathlib import Path

_THIS = Path(__file__).resolve().parent
_BACKEND = _THIS.parent
for _p in (str(_BACKEND), str(_THIS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import app.config as config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.agent_management import router as agent_mgmt_router
from app.services.auth_service import get_current_user
from app.database import init_db

_USER = {"id": 1, "username": "admin", "role": "admin"}


def _build_client() -> tuple[TestClient, str]:
    fd, path = tempfile.mkstemp(suffix=".db", prefix="qa_preset_use_")
    os.close(fd)
    config.settings.DB_PATH = path
    init_db()
    app = FastAPI()
    app.include_router(agent_mgmt_router)
    app.dependency_overrides[get_current_user] = lambda: _USER
    return TestClient(app), path


def _cleanup(path: str) -> None:
    for suffix in ("", "-wal", "-shm"):
        p = path + suffix
        if os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass


def _create_preset(client: TestClient, name: str, **extra) -> dict:
    payload = {
        "name": name,
        "description": "preset e2e",
        "agents": ["agent-a", "agent-b"],
        "category": "分析",
        "tags": ["tag1", "tag2"],
    }
    payload.update(extra)
    resp = client.post("/api/agent-management/pipeline/presets", json=payload)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["code"] == 0, body
    return body["data"]


class TestUsePresetEndpoint:
    def test_create_captures_meta_and_author(self):
        client, path = _build_client()
        try:
            p = _create_preset(client, "use_e2e_meta")
            assert p["author"] == "admin"          # 来自 dependency_overrides 用户
            assert p["category"] == "分析"
            assert p["tags"] == ["tag1", "tag2"]
            assert p["usage_count"] == 0
        finally:
            _cleanup(path)

    def test_use_increments_usage_and_sets_last_used(self):
        client, path = _build_client()
        try:
            p = _create_preset(client, "use_e2e_inc")
            resp = client.post(f"/api/agent-management/pipeline/presets/{p['id']}/use")
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["code"] == 0, body
            # 再次 GET 列表确认 usage_count 已 +1
            lst = client.get("/api/agent-management/pipeline/presets").json()["data"]
            target = next(x for x in lst if x["id"] == p["id"])
            assert target["usage_count"] == 1
            assert target["last_used_at"]           # 非空
        finally:
            _cleanup(path)

    def test_use_cumulative(self):
        client, path = _build_client()
        try:
            p = _create_preset(client, "use_e2e_cum")
            for _ in range(3):
                r = client.post(f"/api/agent-management/pipeline/presets/{p['id']}/use")
                assert r.status_code == 200, r.text
            lst = client.get("/api/agent-management/pipeline/presets").json()["data"]
            target = next(x for x in lst if x["id"] == p["id"])
            assert target["usage_count"] == 3
        finally:
            _cleanup(path)

    def test_use_missing_returns_404(self):
        client, path = _build_client()
        try:
            resp = client.post("/api/agent-management/pipeline/presets/99999999/use")
            assert resp.status_code == 404, resp.text
        finally:
            _cleanup(path)

    def test_defaults_when_meta_omitted(self):
        client, path = _build_client()
        try:
            # 前端 onSaveAs 只发 name/description/agents（省略 category/tags）→ 走缺省
            payload = {
                "name": "use_e2e_defaults",
                "description": "no meta",
                "agents": ["agent-a"],
            }
            resp = client.post("/api/agent-management/pipeline/presets", json=payload)
            assert resp.status_code == 201, resp.text
            p = resp.json()["data"]
            assert p["category"] == "other"
            assert p["tags"] == []
            assert p["author"] == "admin"
            assert p["usage_count"] == 0
        finally:
            _cleanup(path)
