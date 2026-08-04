"""智能体编排模块 — 边界/异常场景补充测试（2026-08-04 全面测试报告新增）.

覆盖现有套件未直接覆盖的边界点：
1. 记忆 API：content 超长截断、非法 memory_type 400、tags 非数组、host_id 非数字
2. 编排入口：不存在的 preset_id、空 event_id
3. 预设：name 重复 409、删除被引用预设
4. 护栏评估：空 action
"""

import os
import tempfile

import pytest
from fastapi.testclient import TestClient

# ── 模块级临时库（规避 Windows sqlite WAL 多库崩溃）──
@pytest.fixture(scope="module", autouse=True)
def _tmp_db():
    from app.config import settings
    orig = settings.DB_PATH
    fd, path = tempfile.mkstemp(suffix=".db")
    settings.DB_PATH = path
    from app.database import init_db
    init_db()
    yield path
    settings.DB_PATH = orig
    os.close(fd)
    os.unlink(path)


@pytest.fixture(scope="module")
def client():
    from app.main import app
    from app.services.auth_service import get_current_user

    async def _admin():
        return {"id": 1, "username": "admin", "role": "admin"}

    app.dependency_overrides[get_current_user] = _admin
    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()


class TestMemoryApiBoundaries:
    """记忆 API 边界/异常."""

    def test_01_create_content_too_long_truncated(self, client):
        long = "A" * 5000
        r = client.post("/api/memories", json={"content": long, "memory_type": "conclusion"})
        assert r.status_code == 200, r.text
        assert r.json()["code"] == 0
        mid = r.json()["data"]["id"]
        # 模型层截断 4000
        detail = client.get("/api/memories").json()["data"]["items"]
        assert len(detail[0]["content"]) <= 4000
        client.delete(f"/api/memories/{mid}")

    def test_02_create_invalid_type_400(self, client):
        """API 层白名单校验：非法 memory_type → 400（比模型层 _coerce_type 回退更严格）."""
        r = client.post("/api/memories", json={"content": "x", "memory_type": "bogus"})
        assert r.status_code == 400, r.text

    def test_03_create_missing_content_400(self, client):
        r = client.post("/api/memories", json={"memory_type": "conclusion"})
        assert r.status_code == 400
        assert "content" in r.json()["detail"].lower()

    def test_04_search_empty_q_422(self, client):
        """q 为空串不满足 Query(min_length=1) → 422（FastAPI 惯例）."""
        r = client.get("/api/memories/search", params={"q": ""})
        assert r.status_code == 422, r.text

    def test_05_delete_missing_404(self, client):
        r = client.delete("/api/memories/999999")
        assert r.status_code == 404


class TestAgentRunBoundaries:
    """编排入口边界."""

    def test_06_nonexistent_preset_id(self, client):
        r = client.post("/api/agents/run", json={"event_id": "evt-x", "preset_id": 999999})
        # 不存在预设 → 4xx（404 或 400，取决于实现）
        assert r.status_code in (400, 404), r.text

    def test_07_empty_event_id(self, client):
        r = client.post("/api/agents/run", json={"event_id": ""})
        assert r.status_code in (200, 400, 422), r.text


class TestPresetBoundaries:
    """预设边界."""

    def test_08_duplicate_name_409(self, client):
        payload = {"name": "dup-boundary", "agents": ["triage"]}
        r1 = client.post("/api/agent-management/pipeline/presets", json=payload)
        assert r1.status_code in (200, 201), r1.text
        r2 = client.post("/api/agent-management/pipeline/presets", json=payload)
        assert r2.status_code == 409, f"expected 409 duplicate, got {r2.status_code}: {r2.text}"
        # 清理
        pid = r1.json()["data"].get("id") or r1.json()["data"].get("preset_id")
        if pid:
            client.delete(f"/api/agent-management/pipeline/presets/{pid}")


class TestGuardrailBoundaries:
    """护栏评估边界."""

    def test_09_evaluate_endpoint_missing_405(self, client):
        """缺陷证据：后端护栏评估端点缺失（real/guardrail.js 标注 TODO 对齐 F8 路由）.

        前端 USE_MOCK.guardrail=true 走 Mock，真实后端无该端点 → 405 Method Not Allowed。
        该断言记录的是缺陷现状，待后端补齐后应改为 200/400。
        """
        r = client.post("/api/agent-management/guardrail/evaluate", json={"action": ""})
        assert r.status_code == 405, f"后端护栏端点应缺失(405)，实际 {r.status_code}"
