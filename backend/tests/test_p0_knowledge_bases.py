"""P0 测试：知识库聚合端点真实化（GET /api/knowledge/bases）。

依据：
- 记忆RAG模块审计报告 §5 P0 方案（页面展示真实 ir_rules 统计，替代写死元数据）
- p0-dev.md（行级实现 + 自测 + 偏差）

验证目标：
1. 返回结构 ``{code, data: {bases, stats, drafts}, message}`` 中无写死假元数据：
   - ``doc_count`` 读取真实 collection.count()（动态，非写死 1）
   - ``embedding_model`` 为真实模型名 ``BAAI/bge-base-zh-v1.5``（非占位 text-embedding-3-small）
   - ``collection_ready`` 由 collection 是否可用派生（动态）
   - ``vector_store="Chroma"`` 为常量标识（区分"真实常量"与"假元数据"）
2. fail-safe：chroma 不可用（``_get_collection`` 返回 None / 抛异常）→
   ``doc_count=0``、``collection_ready=false``、``bases=[]``，不抛异常
3. draft 数据来自 ``KnowledgeDraft.list_approved()`` 真实草稿（含空表与异常降级）

DB 走隔离临时 SQLite（绝不触碰 backend/data/ir_platform.db）。
鉴权用 dependency_overrides 注入 admin 用户，避免真实 token。
chroma/embedding 通过 unittest.mock 在 knowledge_bases 模块命名空间打桩（本机未装 chromadb，
collection-ready 路径为 mock 覆盖，fail-safe 路径为真实环境预期行为）。
"""

import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

_THIS = Path(__file__).resolve().parent
_BACKEND = _THIS.parent
for _p in (str(_BACKEND), str(_THIS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.auth_service import get_current_user
from app.services.knowledge_retriever import EMBEDDING_MODEL_NAME, COLLECTION_NAME

_USER = {"id": 1, "username": "admin", "role": "admin"}

# 旧写死假值（P0 前占位），用于断言已移除
_FAKE_EMBEDDING_MODEL = "text-embedding-3-small"


class FakeCollection:
    """模拟 chromadb collection：仅暴露端点用到的 count() / metadata."""

    def __init__(self, count: int = 0, metadata: dict | None = None):
        self._count = count
        self.metadata = metadata or {}

    def count(self) -> int:
        return self._count


def _build_app(override_auth: bool = True) -> tuple[FastAPI, str]:
    """创建隔离临时库 + 最小 app（仅挂载 knowledge_bases 路由），返回 app 与 db 路径。"""
    from app.config import settings
    from app.database import init_db
    from app.api.knowledge_bases import router as kb_router

    fd, path = tempfile.mkstemp(suffix=".db", prefix="qa_p0_kb_")
    os.close(fd)
    settings.DB_PATH = path
    Path(settings.DATA_DIR).mkdir(parents=True, exist_ok=True)
    init_db()

    app = FastAPI()
    app.include_router(kb_router, prefix="/api/knowledge", tags=["知识库"])
    if override_auth:
        app.dependency_overrides[get_current_user] = lambda: _USER
    return app, path


@contextmanager
def _client(override_auth: bool = True):
    """yield (client, db_path)；结束后清理临时库及其 WAL/SHM 附属文件。"""
    app, path = _build_app(override_auth=override_auth)
    try:
        with TestClient(app) as client:
            yield client, path
    finally:
        for suffix in ("", "-wal", "-shm"):
            p = path + suffix
            if os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass


# ============================================================================
# 1) collection-ready 路径（mock 覆盖真实 chroma）
# ============================================================================


class TestCollectionReadyPath:
    def test_collection_ready_returns_real_stats(self):
        """mock _get_collection 返回 count=37 的假 collection → doc_count=37、ready=true、
        bases[0].kb_id='ir_rules'、embedding_model 为真实模型名，无写死假值。"""
        with _client() as (client, _):
            with (
                patch(
                    "app.api.knowledge_bases._get_collection",
                    return_value=FakeCollection(count=37),
                ),
                patch(
                    "app.api.knowledge_bases._get_embedding_model",
                    return_value=object(),  # 非 None → 端点采用真实模型常量
                ),
            ):
                resp = client.get("/api/knowledge/bases")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == "success"

        data = body["data"]
        # ── stats 动态真实值 ──
        assert data["stats"]["doc_count"] == 37
        assert data["stats"]["collection_ready"] is True
        assert data["stats"]["embedding_model"] == EMBEDDING_MODEL_NAME
        # vector_store 为常量标识（真实 Chroma），允许保留
        assert data["stats"]["vector_store"] == "Chroma"

        # ── bases 真实条目 ──
        assert len(data["bases"]) == 1
        kb = data["bases"][0]
        assert kb["kb_id"] == COLLECTION_NAME  # "ir_rules"
        assert kb["kb_id"] == "ir_rules"
        assert kb["doc_count"] == 37
        assert kb["embedding_model"] == EMBEDDING_MODEL_NAME
        assert kb["vector_store"] == "Chroma"

        # ── 断言旧写死假值已移除 ──
        assert _FAKE_EMBEDDING_MODEL not in resp.text
        assert data["stats"]["doc_count"] != 1  # 不再每条草稿计 1

    def test_index_updated_at_read_from_collection_metadata(self):
        """collection metadata 存在 index_updated_at 时，stats/bases 读取到该值。"""
        ts = "2026-08-01T08:30:00"
        with _client() as (client, _):
            with (
                patch(
                    "app.api.knowledge_bases._get_collection",
                    return_value=FakeCollection(
                        count=5,
                        metadata={"index_updated_at": ts, "hnsw:space": "cosine"},
                    ),
                ),
                patch(
                    "app.api.knowledge_bases._get_embedding_model",
                    return_value=object(),
                ),
            ):
                resp = client.get("/api/knowledge/bases")
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["stats"]["index_updated_at"] == ts
        assert data["bases"][0]["index_updated_at"] == ts

    def test_index_updated_at_empty_when_metadata_absent(self):
        """collection metadata 无时间戳字段时 index_updated_at 恒为 ''（如实返回，不编造）。"""
        with _client() as (client, _):
            with (
                patch(
                    "app.api.knowledge_bases._get_collection",
                    return_value=FakeCollection(count=3, metadata={"hnsw:space": "cosine"}),
                ),
                patch(
                    "app.api.knowledge_bases._get_embedding_model",
                    return_value=object(),
                ),
            ):
                resp = client.get("/api/knowledge/bases")
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["stats"]["index_updated_at"] == ""
        assert data["bases"][0]["index_updated_at"] == ""


# ============================================================================
# 2) fail-safe 路径（chroma 不可用）
# ============================================================================


class TestFailSafe:
    def test_collection_none_returns_degraded_stats(self):
        """_get_collection 返回 None → doc_count=0、collection_ready=false、bases=[]、不抛异常。"""
        with _client() as (client, _):
            with (
                patch("app.api.knowledge_bases._get_collection", return_value=None),
                patch("app.api.knowledge_bases._get_embedding_model", return_value=None),
            ):
                resp = client.get("/api/knowledge/bases")
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["stats"]["doc_count"] == 0
        assert data["stats"]["collection_ready"] is False
        assert data["stats"]["embedding_model"] == "n/a"
        assert data["bases"] == []
        assert data["drafts"] == []

    def test_get_collection_raises_returns_degraded_stats(self):
        """_get_collection 抛异常 → 端点内部捕获，仍返回降级结构，不 500。"""
        with _client() as (client, _):
            with (
                patch(
                    "app.api.knowledge_bases._get_collection",
                    side_effect=RuntimeError("chroma down"),
                ),
                patch(
                    "app.api.knowledge_bases._get_embedding_model",
                    side_effect=RuntimeError("model down"),
                ),
            ):
                resp = client.get("/api/knowledge/bases")
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["stats"]["doc_count"] == 0
        assert data["stats"]["collection_ready"] is False
        assert data["stats"]["embedding_model"] == "n/a"
        assert data["bases"] == []


# ============================================================================
# 3) drafts 数据（真实草稿 + 空表 + 异常降级）
# ============================================================================


class TestDrafts:
    def test_drafts_from_approved_real(self):
        """有已批准草稿 → drafts 非空且字段精简（id/title/category/severity/reviewed_at）。"""
        from app.models.knowledge_draft import KnowledgeDraft

        with _client() as (client, _):
            d1 = KnowledgeDraft.create(
                title="新增恶意软件 XYZ",
                description="内存马检测规则",
                category="malware",
                severity="high",
            )
            KnowledgeDraft.approve(d1["id"])
            d2 = KnowledgeDraft.create(
                title="C2 回连特征",
                description="beacon 外联",
                category="c2_framework",
                severity="critical",
            )
            KnowledgeDraft.approve(d2["id"])
            # 未批准草稿不应出现在 drafts
            KnowledgeDraft.create(title="待审草稿", description="pending", category="auto")

            with (
                patch(
                    "app.api.knowledge_bases._get_collection",
                    return_value=FakeCollection(count=1),
                ),
                patch(
                    "app.api.knowledge_bases._get_embedding_model",
                    return_value=object(),
                ),
            ):
                resp = client.get("/api/knowledge/bases")
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["stats"]["approved_drafts"] == 2
        assert len(data["drafts"]) == 2
        titles = {d["title"] for d in data["drafts"]}
        assert titles == {"新增恶意软件 XYZ", "C2 回连特征"}
        for draft in data["drafts"]:
            assert set(draft.keys()) == {
                "id",
                "title",
                "category",
                "severity",
                "reviewed_at",
            }
        # 字段精简：不携带 description/pattern/raw_ioc 等大字段
        assert all("description" not in d for d in data["drafts"])

    def test_no_drafts_returns_empty(self):
        """草稿表为空 → drafts=[]、approved_drafts=0，不报错。"""
        with _client() as (client, _):
            with (
                patch(
                    "app.api.knowledge_bases._get_collection",
                    return_value=FakeCollection(count=0),
                ),
                patch(
                    "app.api.knowledge_bases._get_embedding_model",
                    return_value=None,
                ),
            ):
                resp = client.get("/api/knowledge/bases")
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["drafts"] == []
        assert data["stats"]["approved_drafts"] == 0

    def test_draft_load_fail_safe(self):
        """list_approved 抛异常 → drafts=[] 且端点不 500（fail-safe）。"""
        with _client() as (client, _):
            with (
                patch(
                    "app.api.knowledge_bases.KnowledgeDraft.list_approved",
                    side_effect=RuntimeError("db locked"),
                ),
                patch(
                    "app.api.knowledge_bases._get_collection",
                    return_value=None,
                ),
                patch("app.api.knowledge_bases._get_embedding_model", return_value=None),
            ):
                resp = client.get("/api/knowledge/bases")
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["drafts"] == []
        assert data["stats"]["approved_drafts"] == 0


# ============================================================================
# 4) 鉴权
# ============================================================================


class TestAuth:
    def test_requires_login(self):
        """未注入当前用户且无 Authorization 头 → 401（端点需要登录）。"""
        with _client(override_auth=False) as (client, _):
            resp = client.get("/api/knowledge/bases")
        assert resp.status_code == 401, resp.text


if __name__ == "__main__":  # pragma: no cover - 便于直接 python 运行冒烟
    sys.exit(pytest.main([__file__, "-v"]))
