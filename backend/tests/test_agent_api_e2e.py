"""Fix A 集成联调测试：通过 FastAPI TestClient 验证 Agent 增改接口回显 tools / model_profile。

覆盖：
- POST /api/agent-management/agents 创建后，响应 data.tools / data.model_profile 与入参一致。
- PUT /api/agent-management/agents/{name} 更新后，响应回显新值。
- 未传 tools / model_profile 时，响应回显默认 [] / ''。

DB 走隔离临时 SQLite（绝不触碰 backend/data/ir.db）。
鉴权用 dependency_overrides 注入 admin 用户，避免真实 token。
"""

import os
import tempfile
from pathlib import Path

import sys

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
    """创建隔离临时库 + 最小 app（仅挂载 agent_management 路由），返回 client 与 db 路径。"""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="qa_fixa_e2e_")
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


def _create(client: TestClient, name: str, **extra) -> dict:
    payload = {
        "name": name,
        "display_name": f"Display {name}",
        "description": "e2e agent",
        "data_sources": ["mail"],
        "depends_on": [],
        "tools": ["tool-x"],
        "model_profile": "profile-y",
    }
    payload.update(extra)
    resp = client.post("/api/agent-management/agents", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


class TestAgentApiE2E:
    def test_create_echoes_tools_and_model_profile(self):
        client, path = _build_client()
        try:
            body = _create(client, "e2e1")
            data = body["data"]
            assert data["tools"] == ["tool-x"]
            assert data["model_profile"] == "profile-y"
        finally:
            _cleanup(path)

    def test_get_after_create_matches_input(self):
        client, path = _build_client()
        try:
            _create(client, "e2e2", tools=["a", "b"], model_profile="mp1")
            # 列表接口 GET /api/agent-management/agents 经 to_dict 回显，天然含新字段
            resp = client.get("/api/agent-management/agents")
            assert resp.status_code == 200, resp.text
            agents = resp.json()["data"]
            found = next((a for a in agents if a["name"] == "e2e2"), None)
            assert found is not None, "created agent should appear in list"
            assert found["tools"] == ["a", "b"]
            assert found["model_profile"] == "mp1"
        finally:
            _cleanup(path)

    def test_update_echoes_tools_and_model_profile(self):
        client, path = _build_client()
        try:
            _create(client, "e2e3")
            resp = client.put(
                "/api/agent-management/agents/e2e3",
                json={"tools": ["t1", "t2"], "model_profile": "mp2"},
            )
            assert resp.status_code == 200, resp.text
            data = resp.json()["data"]
            assert data["tools"] == ["t1", "t2"]
            assert data["model_profile"] == "mp2"
        finally:
            _cleanup(path)

    def test_defaults_when_omitted(self):
        client, path = _build_client()
        try:
            payload = {
                "name": "e2e4",
                "display_name": "Display e2e4",
            }
            resp = client.post("/api/agent-management/agents", json=payload)
            assert resp.status_code == 201, resp.text
            data = resp.json()["data"]
            assert data["tools"] == []
            assert data["model_profile"] == ""
        finally:
            _cleanup(path)
