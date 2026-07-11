"""知识库检索器单元测试 — 验证 Bug1 / Bug2 修复与安全缺口封堵.

运行方式（必须在 backend/ 目录下执行，使用项目 venv，避免系统 python 缺 bcrypt）:

    cd backend
    venv/Scripts/python -m pytest tests/test_knowledge_retriever.py -v

覆盖点:
    1. 种子(10 条)确实进入向量库                          -> 验证 Bug1 真正修复
    2. 索引幂等（_seed_or_draft_exists 守卫）            -> 重复构建不重复
    3. 已批准草稿进入向量库（draft_<id>，source=draft）   -> 草稿纳入检索
    4. reject / recall 触发重建后向量删除（10 条 seed 仍在）-> 验证 Bug2
    5. 关键词回退路径（_EMBEDDING_AVAILABLE=False）        -> 返回结构化 list[dict]
    6. 向量检索返回结构（title/summary/confidence/score）  -> 与 prompt_builder 契约
    7. 接口鉴权（无 token -> 401/403；有 token -> 200；
       reject/recall 端点确实调用 rebuild_seed_index）      -> 验证安全缺口封堵

Mock 策略（避免下载 all-MiniLM-L6-v2 ~80MB）:
    - patch knowledge_retriever._get_embedding_model -> 返回 384 维确定性 stub
      （对所有输入返回相同常量向量，使向量路径真正跑通并能产生命中）
    - patch knowledge_retriever._get_collection -> 返回 chromadb.Client() 内存库
      （ephemeral，不碰 backend/data/chroma 持久化目录、不碰生产库）
    - 显式置 _CHROMA_AVAILABLE=True / _EMBEDDING_AVAILABLE=True
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

# 保证 backend/ 在 sys.path（python -m pytest 从 backend/ 运行时已含 cwd，这里再兜底）
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import app.config as config  # noqa: E402
from app.services import knowledge_retriever as kr  # noqa: E402


# 期望的内置种子 ID（前缀 seed_，序号 0-9，共 10 条）
EXPECTED_SEED_IDS = [
    "seed_0_T1059.001",
    "seed_1_T1546.003",
    "seed_2_T1547",
    "seed_3_T1055",
    "seed_4_T1071",
    "seed_5_Cobalt Strike",
    "seed_6_Metasploit Framework",
    "seed_7_PowerShell Empire",
    "seed_8_勒索软件行为模式",
    "seed_9_窃密木马行为模式",
]


class _StubEmbeddingModel:
    """确定性、不需联网下载的 embedding 桩.

    返回固定维度(384)向量。对所有输入返回相同常量向量 ->
    任意 query 与任意 doc 的 cosine distance = 0，从而向量检索
    必定返回结果（用于验证「向量路径真正跑通」与结构化返回契约）。
    encode 同时支持单条字符串与字符串列表两种入参。
    """

    DIM = 384

    def encode(self, texts, **kwargs):
        if isinstance(texts, str):
            texts = [texts]
        arr = np.full((len(texts), self.DIM), 0.01, dtype=np.float32)
        return arr


class TestKnowledgeRetriever(unittest.TestCase):
    """知识库检索器：向量索引 / 幂等 / 草稿入向量库 / reject-recall 重建 /
    关键词回退 / 向量返回结构。
    """

    def setUp(self):
        # 1) 隔离 SQLite：临时 DB + init_db（供已批准草稿读取）
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        config.settings.DB_PATH = self.tmp.name
        from app.database import init_db

        init_db()

        # 2) 重置 knowledge_retriever 模块级状态（进程级缓存 / 单例 / 可用性开关）
        kr._COLLECTION = None
        kr._EMBEDDING_MODEL = None
        kr._SEED_CACHE = []
        kr._SEED_INDEXED = False
        kr._CHROMA_AVAILABLE = True
        kr._EMBEDDING_AVAILABLE = True
        kr.KnowledgeRetriever._index_initialized = False

        # 3) 隔离 Chroma：每次测试新建 ephemeral 内存 collection（不碰持久化目录）
        import chromadb

        self.chroma_client = chromadb.Client()
        self.collection = self.chroma_client.get_or_create_collection(
            name=kr.COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )

        # 4) patch _get_collection -> ephemeral；_get_embedding_model -> stub
        self.patchers = []
        p1 = mock.patch.object(kr, "_get_collection", return_value=self.collection)
        p1.start()
        self.patchers.append(p1)
        self.stub_model = _StubEmbeddingModel()
        p2 = mock.patch.object(kr, "_get_embedding_model", return_value=self.stub_model)
        p2.start()
        self.patchers.append(p2)

    def tearDown(self):
        for p in self.patchers:
            p.stop()
        kr._COLLECTION = None
        kr._EMBEDDING_MODEL = None
        kr._SEED_CACHE = []
        kr._SEED_INDEXED = False
        kr._CHROMA_AVAILABLE = True
        kr._EMBEDDING_AVAILABLE = True
        kr.KnowledgeRetriever._index_initialized = False
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    # ── 1. 种子确实入向量库（验证 Bug1 真正修复）───────────────────
    def test_1_seeds_indexed_into_vector_store(self):
        kr.KnowledgeRetriever._ensure_index()

        res = self.collection.get(where={"source": "seed"})
        ids = set(res["ids"])
        for sid in EXPECTED_SEED_IDS:
            self.assertIn(sid, ids, f"种子 {sid} 未进入向量库（Bug1 可能未修复）")
        self.assertEqual(len(ids), 10, f"种子数量应为 10，实际 {len(ids)}: {sorted(ids)}")

    # ── 2. 索引幂等（_seed_or_draft_exists 守卫）────────────────────
    def test_2_seed_index_idempotent(self):
        kr.KnowledgeRetriever._ensure_index()
        # 模拟「再次构建」：复位 _index_initialized 守卫，重新走 _ensure_index
        kr.KnowledgeRetriever._index_initialized = False
        kr.KnowledgeRetriever._ensure_index()

        res = self.collection.get(where={"source": "seed"})
        ids = res["ids"]
        self.assertEqual(len(ids), 10, f"重复构建后种子应仍为 10 条，实际 {len(ids)}")
        self.assertEqual(len(ids), len(set(ids)), "存在重复种子 ID（幂等失效）")

    # ── 3. 已批准草稿进入向量库 ─────────────────────────────────────
    def test_3_approved_draft_indexed(self):
        from app.models.knowledge_draft import KnowledgeDraft

        draft = KnowledgeDraft.create(
            title="测试恶意工具 X",
            description="用于验证已批准草稿进入向量库",
            category="malware",
            severity="high",
            source="manual",
        )
        draft_id = draft["id"]
        self.assertEqual(draft["status"], "pending")

        KnowledgeDraft.approve(draft_id)
        # 与 API approve 一致：批准后立即触发重建
        kr.KnowledgeRetriever.rebuild_seed_index()

        res = self.collection.get(ids=[f"draft_{draft_id}"])
        self.assertTrue(res["ids"], "已批准草稿应进入向量库")
        self.assertEqual(res["metadatas"][0]["source"], "draft")

    # ── 4. reject / recall 触发重建后向量删除（核心回归，验证 Bug2）──
    def test_4_reject_and_recall_trigger_rebuild(self):
        from app.database import get_connection
        from app.models.knowledge_draft import KnowledgeDraft

        draft = KnowledgeDraft.create(
            title="撤回/拒绝回归测试 Z",
            description="验证 reject/recall 触发的重建会移除已批准草稿向量",
            category="malware",
            severity="high",
            source="manual",
        )
        draft_id = draft["id"]
        did = f"draft_{draft_id}"

        # 批准 -> 向量库应出现该草稿
        KnowledgeDraft.approve(draft_id)
        kr.KnowledgeRetriever.rebuild_seed_index()
        self.assertTrue(
            self.collection.get(ids=[did])["ids"], "批准后草稿应入向量库"
        )

        # recall 路径（recall_draft 端点同样会调 rebuild_seed_index）
        KnowledgeDraft.recall(draft_id)  # approved -> pending
        kr.KnowledgeRetriever.rebuild_seed_index()
        self.assertFalse(
            self.collection.get(ids=[did])["ids"],
            "recall 后重建应移除该草稿向量（Bug2 回归）",
        )
        self.assertEqual(
            len(self.collection.get(where={"source": "seed"})["ids"]),
            10,
            "recall 后种子应仍为 10 条",
        )

        # 再次批准 -> 重新入向量库
        KnowledgeDraft.approve(draft_id)
        kr.KnowledgeRetriever.rebuild_seed_index()
        self.assertTrue(
            self.collection.get(ids=[did])["ids"], "二次批准后应重新入向量库"
        )

        # reject 路径：复现 reject_draft 将 status 置为 rejected 后的状态，再触发重建
        # （注：模型 reject() 仅允许从 pending 调用，故此处直接复现其写入的
        #  SQLite 状态，验证 rebuild_seed_index 会据此移除该草稿向量）
        with get_connection() as conn:
            conn.execute(
                "UPDATE knowledge_drafts SET status='rejected', reviewed_at='x' WHERE id=?",
                (draft_id,),
            )
        kr.KnowledgeRetriever.rebuild_seed_index()
        self.assertFalse(
            self.collection.get(ids=[did])["ids"],
            "reject 后重建应移除该草稿向量（Bug2 回归）",
        )
        self.assertEqual(
            len(self.collection.get(where={"source": "seed"})["ids"]),
            10,
            "reject 后种子应仍为 10 条",
        )

    # ── 5. 关键词回退路径（关闭向量，验证结构化返回且不报错）────────
    def test_5_keyword_fallback_returns_structured(self):
        kr._EMBEDDING_AVAILABLE = False  # 关闭向量，强制走关键词回退
        kr.KnowledgeRetriever._index_initialized = False

        tiered = {
            "host_basic": {
                "hostname": "WIN-ABC",
                "ip_address": "10.0.0.5",
                "os_type": "Windows",
            },
            "abnormal_processes_high": [
                {"name": "Cobalt Strike", "cmd": "beacon.exe", "reason": "C2 beacon"},
            ],
            "analysis_result": {"risk_level": "high", "summary": "发现 C2 框架特征"},
        }

        results = kr.KnowledgeRetriever.retrieve(tiered, limit=5, structured=True)
        self.assertIsInstance(results, list)
        self.assertTrue(results, "关键词回退未命中任何种子（可能种子未加载）")
        for item in results:
            self.assertIsInstance(item, dict)
            for key in ("title", "summary", "confidence", "score", "source"):
                self.assertIn(key, item)
            self.assertTrue(item.get("title"))

    # ── 6. 向量检索返回结构（与 prompt_builder 拼接契约一致）────────
    def test_6_vector_retrieve_returns_structured(self):
        kr.KnowledgeRetriever._ensure_index()
        self.assertGreater(self.collection.count(), 0, "向量库应为非空")

        tiered = {
            "host_basic": {
                "hostname": "WIN-XYZ",
                "ip_address": "10.0.0.9",
                "os_type": "Windows",
            },
            "analysis_result": {
                "risk_level": "critical",
                "summary": "Cobalt Strike 反弹 shell 与 beacon 心跳",
            },
            "abnormal_processes_high": [{"name": "Cobalt Strike", "reason": "C2"}],
        }

        results = kr.KnowledgeRetriever.retrieve(tiered, limit=5, structured=True)
        self.assertIsInstance(results, list)
        self.assertTrue(results, "向量检索应返回至少一条结构化结果")
        for item in results:
            self.assertIsInstance(item, dict)
            for key in ("title", "summary", "confidence", "score", "source"):
                self.assertIn(key, item)
            self.assertTrue(item.get("title"))


class TestKnowledgeDraftAuth(unittest.TestCase):
    """知识草稿接口鉴权（验证安全缺口封堵：全部路由加 Depends(get_current_user)）。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        cls.tmp.close()
        config.settings.DB_PATH = cls.tmp.name

        from app.database import init_db

        init_db()

        from app.main import app
        from fastapi.testclient import TestClient

        cls.app = app
        cls.client = TestClient(app)

        resp = cls.client.post(
            "/api/auth/login", json={"username": "admin", "password": "admin123"}
        )
        assert resp.status_code == 200, f"登录失败: {resp.text}"
        cls.token = resp.json()["data"]["token"]
        cls.headers = {"Authorization": f"Bearer {cls.token}"}

    @classmethod
    def tearDownClass(cls):
        try:
            os.unlink(cls.tmp.name)
        except OSError:
            pass

    # ── 无 token -> 401/403 ──────────────────────────────────────
    def test_no_auth_drafts_returns_401(self):
        resp = self.client.get("/api/knowledge/drafts")
        self.assertIn(resp.status_code, (401, 403))

    def test_no_auth_seeds_returns_401(self):
        resp = self.client.get("/api/knowledge/seeds")
        self.assertIn(resp.status_code, (401, 403))

    def test_no_auth_reject_returns_401(self):
        resp = self.client.post("/api/knowledge/drafts/999/reject")
        self.assertIn(resp.status_code, (401, 403))

    # ── 有 token -> 200 ──────────────────────────────────────────
    def test_auth_seeds_returns_200(self):
        resp = self.client.get("/api/knowledge/seeds", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["code"], 0)
        self.assertEqual(len(body["data"]), 10, "内置种子应为 10 条")

    def test_auth_drafts_returns_200(self):
        resp = self.client.get("/api/knowledge/drafts", headers=self.headers)
        self.assertEqual(resp.status_code, 200)

    # ── reject / recall 端点确实触发 rebuild_seed_index（Bug2 回归）─
    def test_reject_endpoint_triggers_rebuild(self):
        import app.services.knowledge_retriever as krmod
        from app.models.knowledge_draft import KnowledgeDraft

        draft = KnowledgeDraft.create(
            title="鉴权回归草稿",
            description="验证 reject 触发重建",
            category="auto",
            severity="medium",
            source="manual",
        )
        did = draft["id"]
        with mock.patch.object(
            krmod.KnowledgeRetriever, "rebuild_seed_index", return_value=True
        ) as m:
            resp = self.client.post(
                f"/api/knowledge/drafts/{did}/reject", headers=self.headers
            )
            self.assertEqual(resp.status_code, 200)
            self.assertTrue(m.called, "reject_draft 必须调用 rebuild_seed_index()（Bug2 回归）")

    def test_recall_endpoint_triggers_rebuild(self):
        import app.services.knowledge_retriever as krmod
        from app.models.knowledge_draft import KnowledgeDraft

        draft = KnowledgeDraft.create(
            title="鉴权回归草稿2",
            description="验证 recall 触发重建",
            category="auto",
            severity="medium",
            source="manual",
        )
        KnowledgeDraft.approve(draft["id"])  # 先批准，再撤回
        did = draft["id"]
        with mock.patch.object(
            krmod.KnowledgeRetriever, "rebuild_seed_index", return_value=True
        ) as m:
            resp = self.client.post(
                f"/api/knowledge/drafts/{did}/recall", headers=self.headers
            )
            self.assertEqual(resp.status_code, 200)
            self.assertTrue(m.called, "recall_draft 必须调用 rebuild_seed_index()（Bug2 回归）")


if __name__ == "__main__":
    unittest.main(verbosity=2)
