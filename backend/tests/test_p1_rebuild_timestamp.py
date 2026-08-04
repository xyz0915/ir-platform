"""P1 测试：rebuild 时间戳（_touch_index_metadata + rebuild_seed_index 集成 + 端点联动）。

依据：
- ``p1-design.md`` §3（rebuild 时间戳设计）与 §6 验收标准 C；
- ``p1-dev.md`` §2.2（``knowledge_retriever.py`` ``_touch_index_metadata`` L513-532、
  ``rebuild_seed_index`` 成功分支 L956-967）。

覆盖（按任务 T3）：
- ``_touch_index_metadata`` 写 index_updated_at/updated_at 到 ir_rules + ir_seed，
  合并保留既有 metadata（hnsw:space 等）；
- 时间为 ISO UTC（``datetime.now(timezone.utc).isoformat(timespec="seconds")``）；
- 幂等覆盖（last-write-wins，mock datetime 验证两次写入时间不同）；
- collection 为 None 跳过；异常被吞（logger.warning），不向调用方传播；
- ``rebuild_seed_index()`` 成功（_build_seed_index True）→ 调用 _touch_index_metadata；
  失败（False）→ 不调用；collection 不可用 → 返回 False 不调用；
- 端点联动：写后 GET /api/knowledge/bases 的 stats.index_updated_at / bases[0].index_updated_at
  读到该值（P0 端点零改动自动生效）。

约束：chroma/DB 全部 mock；不触碰真实 data/chroma 持久化集合。
"""

import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.services.knowledge_retriever as kr

_USER = {"id": 1, "username": "admin", "role": "admin"}


class FakeCollection:
    """模拟 chromadb collection：记录 metadata 与 modify 调用。"""

    def __init__(self, metadata=None, ids=None):
        self.metadata = dict(metadata or {})
        self._ids = ids or []
        self.modify_calls = []

    def modify(self, metadata=None, **kwargs):
        self.metadata = dict(metadata or {})
        self.modify_calls.append(dict(metadata or {}))

    def get(self):
        return {"ids": list(self._ids)}

    def delete(self, ids):
        self._ids = [i for i in self._ids if i not in set(ids)]

    def count(self):
        return len(self._ids)


@pytest.fixture()
def _snapshot_kr_globals(monkeypatch):
    """快照/恢复 knowledge_retriever 模块级缓存全局（rebuild 会重置它们）。"""
    monkeypatch.setattr(kr, "_SEED_CACHE", list(kr._SEED_CACHE))
    monkeypatch.setattr(kr, "_SEED_INDEXED", kr._SEED_INDEXED)


# ============================================================================
# _touch_index_metadata
# ============================================================================


class TestTouchIndexMetadata:
    def test_writes_both_collections_preserving_metadata(self, monkeypatch):
        """写 index_updated_at/updated_at 到 ir_rules + ir_seed，合并保留 hnsw:space/other。"""
        rule = FakeCollection(metadata={"hnsw:space": "cosine", "other": 1})
        seed = FakeCollection(metadata={"hnsw:space": "cosine"})
        monkeypatch.setattr(kr, "_get_collection", lambda: rule)
        monkeypatch.setattr(kr, "_get_collection_by_name", lambda name: seed)

        kr._touch_index_metadata()

        assert rule.modify_calls, "ir_rules 应被 modify"
        assert seed.modify_calls, "ir_seed 应被 modify"
        for coll in (rule, seed):
            meta = coll.metadata
            assert "index_updated_at" in meta
            assert "updated_at" in meta
            assert meta["index_updated_at"] == meta["updated_at"]
            assert meta["hnsw:space"] == "cosine"   # 既有 metadata 保留
        assert rule.metadata["other"] == 1
        assert rule.metadata["index_updated_at"] == seed.metadata["index_updated_at"]

    def test_timestamp_is_iso_utc(self, monkeypatch):
        """时间为 ISO UTC（timespec=seconds），可被 fromisoformat 解析。"""
        rule = FakeCollection(metadata={})
        seed = FakeCollection(metadata={})
        monkeypatch.setattr(kr, "_get_collection", lambda: rule)
        monkeypatch.setattr(kr, "_get_collection_by_name", lambda name: seed)

        kr._touch_index_metadata()

        from datetime import datetime
        parsed = datetime.fromisoformat(rule.metadata["index_updated_at"])
        assert parsed.tzinfo is not None  # 含 UTC 时区偏移

    def test_idempotent_last_write_wins(self, monkeypatch):
        """重复 rebuild 覆盖旧时间戳（幂等，last-write-wins）。"""
        rule = FakeCollection(metadata={})
        seed = FakeCollection(metadata={})
        monkeypatch.setattr(kr, "_get_collection", lambda: rule)
        monkeypatch.setattr(kr, "_get_collection_by_name", lambda name: seed)

        class _FakeDT:
            _values = iter([
                "2026-08-04T07:00:00+00:00",
                "2026-08-04T08:00:00+00:00",
            ])

            @classmethod
            def now(cls, tz=None):
                return cls()

            def isoformat(self, timespec="seconds"):
                return next(self._values)

        monkeypatch.setattr(kr, "datetime", _FakeDT)

        kr._touch_index_metadata()
        first = rule.metadata["index_updated_at"]
        kr._touch_index_metadata()
        second = rule.metadata["index_updated_at"]
        assert first == "2026-08-04T07:00:00+00:00"
        assert second == "2026-08-04T08:00:00+00:00"   # 覆盖写，无累积
        assert len(rule.modify_calls) == 2

    def test_none_collections_skipped(self, monkeypatch):
        """两个 collection 均为 None → 跳过不抛。"""
        monkeypatch.setattr(kr, "_get_collection", lambda: None)
        monkeypatch.setattr(kr, "_get_collection_by_name", lambda name: None)
        kr._touch_index_metadata()  # 不应抛异常

    def test_one_none_one_present(self, monkeypatch):
        """仅一个 collection 可用 → 只写可用者，不抛。"""
        rule = FakeCollection(metadata={"hnsw:space": "cosine"})
        monkeypatch.setattr(kr, "_get_collection", lambda: rule)
        monkeypatch.setattr(kr, "_get_collection_by_name", lambda name: None)
        kr._touch_index_metadata()
        assert "index_updated_at" in rule.metadata

    def test_exception_swallowed(self, monkeypatch, caplog):
        """metadata 写入异常被吞（logger.warning），不向调用方传播。"""
        def _boom():
            raise RuntimeError("chroma modify failed")

        monkeypatch.setattr(kr, "_get_collection", _boom)
        monkeypatch.setattr(kr, "_get_collection_by_name", lambda name: FakeCollection())
        kr._touch_index_metadata()  # 不抛
        assert "Failed to write index_updated_at" in caplog.text


# ============================================================================
# rebuild_seed_index 集成
# ============================================================================


class TestRebuildSeedIndex:
    def test_success_calls_touch(self, monkeypatch, _snapshot_kr_globals):
        """rebuild 成功（_build_seed_index True）→ 调用 _touch_index_metadata。"""
        calls = []
        coll = FakeCollection(ids=["seed_a", "draft_b", "other_c"])
        monkeypatch.setattr(kr, "_get_collection_by_name", lambda name: coll)
        monkeypatch.setattr(kr, "_load_seed_data", lambda: [])
        monkeypatch.setattr(kr, "_build_seed_index", lambda: True)
        monkeypatch.setattr(kr, "_EMBEDDING_AVAILABLE", True)
        monkeypatch.setattr(kr, "_touch_index_metadata", lambda: calls.append("touch"))

        result = kr.KnowledgeRetriever.rebuild_seed_index()

        assert result is True
        assert calls == ["touch"]
        # 旧 seed/draft 条目被删除（seed_a、draft_b），other_c 保留
        assert coll._ids == ["other_c"]

    def test_failure_does_not_call_touch(self, monkeypatch, _snapshot_kr_globals):
        """rebuild 失败（_build_seed_index False）→ 不写时间戳。"""
        calls = []
        coll = FakeCollection(ids=["seed_a"])
        monkeypatch.setattr(kr, "_get_collection_by_name", lambda name: coll)
        monkeypatch.setattr(kr, "_load_seed_data", lambda: [])
        monkeypatch.setattr(kr, "_build_seed_index", lambda: False)
        monkeypatch.setattr(kr, "_EMBEDDING_AVAILABLE", True)
        monkeypatch.setattr(kr, "_touch_index_metadata", lambda: calls.append("touch"))

        result = kr.KnowledgeRetriever.rebuild_seed_index()

        assert result is False
        assert calls == []

    def test_collection_unavailable_returns_false(self, monkeypatch, _snapshot_kr_globals):
        """collection 不可用 → 返回 False，不调用 _touch_index_metadata。"""
        calls = []
        monkeypatch.setattr(kr, "_get_collection_by_name", lambda name: None)
        monkeypatch.setattr(kr, "_load_seed_data", lambda: [])
        monkeypatch.setattr(kr, "_EMBEDDING_AVAILABLE", True)
        monkeypatch.setattr(kr, "_touch_index_metadata", lambda: calls.append("touch"))

        result = kr.KnowledgeRetriever.rebuild_seed_index()

        assert result is False
        assert calls == []


# ============================================================================
# 端点联动（P0 端点零改动验证）
# ============================================================================


@contextmanager
def _client():
    """隔离临时 SQLite + 最小 app（仅挂载 knowledge_bases 路由），yield TestClient。"""
    from app.config import settings as app_settings
    from app.database import init_db
    from app.api.knowledge_bases import router as kb_router

    fd, path = tempfile.mkstemp(suffix=".db", prefix="qa_p1_ts_")
    os.close(fd)
    original = app_settings.DB_PATH
    app_settings.DB_PATH = path
    Path(app_settings.DATA_DIR).mkdir(parents=True, exist_ok=True)
    init_db()

    app = FastAPI()
    app.include_router(kb_router, prefix="/api/knowledge", tags=["知识库"])
    app.dependency_overrides[__import__("app.services.auth_service", fromlist=["get_current_user"]).get_current_user] = lambda: _USER
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app_settings.DB_PATH = original
        for suffix in ("", "-wal", "-shm"):
            p = path + suffix
            if os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass


class TestEndpointLinkage:
    def test_touch_then_endpoint_reads_index_updated_at(self, monkeypatch):
        """_touch_index_metadata 写入后 → GET /api/knowledge/bases 自动读到时间戳（端点零改动）。"""
        rule = FakeCollection(metadata={"hnsw:space": "cosine"}, ids=["a", "b"])
        seed = FakeCollection(metadata={"hnsw:space": "cosine"}, ids=["s1"])
        monkeypatch.setattr(kr, "_get_collection", lambda: rule)
        monkeypatch.setattr(kr, "_get_collection_by_name", lambda name: seed)

        # 1) 模拟 rebuild 成功后的时间戳写入
        kr._touch_index_metadata()
        ts = rule.metadata["index_updated_at"]
        assert ts

        # 2) 端点读取（knowledge_bases 命名空间的 _get_collection 打桩指向同一 collection）
        with _client() as client:
            with (
                patch("app.api.knowledge_bases._get_collection", return_value=rule),
                patch("app.api.knowledge_bases._get_embedding_model", return_value=object()),
            ):
                resp = client.get("/api/knowledge/bases")
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["stats"]["index_updated_at"] == ts
        assert data["bases"][0]["index_updated_at"] == ts


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-v"]))
