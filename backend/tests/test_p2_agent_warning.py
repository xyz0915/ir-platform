"""T05-3 P2 单元测试：新建/编辑校验提示（create/update 顶层 warning + kind 兼容别名）。

设计依据：``custom-agent/design.md`` §4（P2 warning 机制）+ 验收标准 §11 P2。

覆盖：
- ``classify_execution_mode`` / ``build_agent_warning`` 纯函数三态：
  已知类型 real（无 warning）/ 未知+配置 custom-real / 未知无配置 summary；
- API create：未知类型无配置 → warning 含「摘要模式」；未知 + tools →
  warning 含「自定义执行」；已知类型（triage）→ 无 warning 字段；
- API update：返回 warning；
- ``data.kind`` 兼容别名存在（custom / built-in）。

**测试速度优化**：纯函数用例零 DB；API 用例共享 session 级 TestClient + 临时
SQLite（init_db 只执行一次），各用例使用唯一 agent 名避免冲突。
鉴权用 dependency_overrides 注入 admin 用户，避免真实 token。
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

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
from app.services.agents.execution_mode import (
    ALL_KNOWN_TYPES,
    BUILTIN_AGENT_NAMES,
    KNOWN_RUNNER_TYPES,
    build_agent_warning,
    classify_execution_mode,
)

_USER = {"id": 1, "username": "admin", "role": "admin"}


def _cleanup(path: str) -> None:
    for suffix in ("", "-wal", "-shm"):
        p = path + suffix
        if os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass


@pytest.fixture(scope="session")
def api_env():
    """session 级隔离临时 SQLite + TestClient（共享，初始化一次）。"""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="qa_p2_warn_")
    os.close(fd)
    config.settings.DB_PATH = path
    init_db()
    app = FastAPI()
    app.include_router(agent_mgmt_router)
    app.dependency_overrides[get_current_user] = lambda: _USER
    client = TestClient(app)
    yield client, path
    _cleanup(path)


class TestExecutionModePure:
    """execution_mode 纯函数三态。"""

    def test_known_type_real(self):
        assert classify_execution_mode("triage", [], "") == "real"
        assert classify_execution_mode("file_analysis", ["t"], "p") == "real"
        assert classify_execution_mode("llm", [], "") == "real"
        assert build_agent_warning("triage", [], "") == ""
        assert build_agent_warning("responder", ["t"], "p") == ""

    def test_unknown_with_tools_custom_real(self):
        assert classify_execution_mode("custom-x", ["t1"], "") == "custom-real"
        assert classify_execution_mode("custom-x", [], "p1") == "custom-real"
        w = build_agent_warning("custom-x", ["t1"], "p1")
        assert "自定义执行" in w
        assert "真实调用" in w

    def test_unknown_without_config_summary(self):
        assert classify_execution_mode("custom-x", [], "") == "summary"
        w = build_agent_warning("custom-x", [], "")
        assert "摘要模式" in w
        assert "建议配置关联工具或模型 Profile" in w

    def test_all_known_types_include_runners_and_builtin(self):
        assert BUILTIN_AGENT_NAMES == {"triage", "responder", "reporter"}
        assert {"file_analysis", "process_analysis", "network_analysis",
                "registry_analysis", "timeline", "root_cause", "threat_intel",
                "branch", "llm", "trigger", "guardrail"} <= KNOWN_RUNNER_TYPES
        assert ALL_KNOWN_TYPES == KNOWN_RUNNER_TYPES | BUILTIN_AGENT_NAMES


class TestAgentWarningApi:
    """API create/update warning 行为（共享 session DB，用例使用唯一名称）。"""

    def test_create_unknown_no_config_warning_summary(self, api_env):
        client, _ = api_env
        resp = client.post("/api/agent-management/agents", json={
            "name": "unk-1", "display_name": "U1",
        })
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert "warning" in body
        assert "摘要模式" in body["warning"]
        # P1 兼容别名：data.kind 存在
        assert body["data"]["kind"] == "custom"

    def test_create_unknown_with_tools_warning_custom(self, api_env):
        client, _ = api_env
        resp = client.post("/api/agent-management/agents", json={
            "name": "unk-2", "display_name": "U2",
            "tools": ["tool-a"], "model_profile": "p1",
        })
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert "warning" in body
        assert "自定义执行" in body["warning"]

    def test_create_known_type_no_warning(self, api_env):
        client, _ = api_env
        resp = client.post("/api/agent-management/agents", json={
            "name": "triage", "display_name": "分诊",
        })
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert "warning" not in body, body

    def test_update_returns_warning(self, api_env):
        client, _ = api_env
        client.post("/api/agent-management/agents", json={
            "name": "upd-1", "display_name": "Upd",
        })
        resp = client.put("/api/agent-management/agents/upd-1", json={
            "tools": ["t1"],
        })
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "warning" in body
        assert "自定义执行" in body["warning"]

    def test_update_known_type_no_warning(self, api_env):
        client, _ = api_env
        client.post("/api/agent-management/agents", json={
            "name": "guardrail", "display_name": "护栏",
        })
        resp = client.put("/api/agent-management/agents/guardrail", json={
            "tools": ["t1"],
        })
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "warning" not in body, body

    def test_data_kind_compat_alias(self, api_env):
        client, _ = api_env
        # custom
        resp = client.post("/api/agent-management/agents", json={
            "name": "kind-custom", "display_name": "KC", "type": "custom",
        })
        assert resp.json()["data"]["kind"] == "custom"
        # built-in
        resp = client.post("/api/agent-management/agents", json={
            "name": "kind-builtin", "display_name": "KB", "type": "built-in",
        })
        assert resp.json()["data"]["kind"] == "built-in"
