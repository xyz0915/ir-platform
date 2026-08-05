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
    - patch knowledge_retriever._get_collection -> 返回 rule 内存 collection
      （ephemeral，供 retrieve() 使用）
    - patch knowledge_retriever._get_collection_by_name -> 按名称返回 seed/rule/draft
      三个 ephemeral collection（A7：索引构建/重建也走内存库，绝不碰生产
      backend/data/chroma；原实现只 patch _get_collection，导致 _build_index/
      rebuild_seed_index 直连持久化库，384 维桩触发维度冲突并可能清空生产索引）
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

        # 3) 隔离 Chroma：每次测试新建独立临时目录 + PersistentClient
        #    （seed/rule/draft 三个 collection，不碰 backend/data/chroma 生产库）。
        #    注意：chromadb 1.x 的 chromadb.Client()/EphemeralClient() 默认共享
        #    进程级 System 单例（实测跨实例可见），必须用唯一 persist_directory。
        import chromadb
        import shutil

        self._chroma_tmp = tempfile.mkdtemp(prefix="qa_chroma_")
        self.chroma_client = chromadb.PersistentClient(
            path=self._chroma_tmp,
            settings=chromadb.Settings(anonymized_telemetry=False),
        )
        self.collections = {
            name: self.chroma_client.get_or_create_collection(
                name=name,
                metadata={"hnsw:space": "cosine"},
            )
            for name in (kr.COLLECTION_NAMES["seed"], kr.COLLECTION_NAMES["rule"], kr.COLLECTION_NAMES["draft"])
        }
        # 兼容旧引用：self.collection = rule collection（retrieve 用）
        self.collection = self.collections[kr.COLLECTION_NAMES["rule"]]

        # 4) patch _get_collection（retrieve）→ rule ephemeral；
        #    patch _get_collection_by_name（索引构建/重建）→ 按名返回 ephemeral；
        #    _get_embedding_model -> 384 维 stub
        self.patchers = []
        p1 = mock.patch.object(kr, "_get_collection", return_value=self.collection)
        p1.start()
        self.patchers.append(p1)
        # A7 关键：索引构建/重建路径全部走内存库，杜绝直连生产 data/chroma
        p3 = mock.patch.object(
            kr,
            "_get_collection_by_name",
            side_effect=lambda name: self.collections.get(name),
        )
        p3.start()
        self.patchers.append(p3)
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
        # 清理隔离 chroma 临时目录（chromadb 内部句柄可能占用，best-effort）
        if getattr(self, "_chroma_tmp", None):
            import shutil

            shutil.rmtree(self._chroma_tmp, ignore_errors=True)
            self._chroma_tmp = None

    # ── 1. 种子确实入向量库（验证 Bug1 真正修复）───────────────────
    def test_1_seeds_indexed_into_vector_store(self):
        kr.KnowledgeRetriever._ensure_index()

        res = self.collections[kr.COLLECTION_NAMES["seed"]].get(where={"source": "seed"})
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

        res = self.collections[kr.COLLECTION_NAMES["seed"]].get(where={"source": "seed"})
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

        res = self.collections[kr.COLLECTION_NAMES["seed"]].get(ids=[f"draft_{draft_id}"])
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
            self.collections[kr.COLLECTION_NAMES["seed"]].get(ids=[did])["ids"],
            "批准后草稿应入向量库",
        )

        # recall 路径（recall_draft 端点同样会调 rebuild_seed_index）
        KnowledgeDraft.recall(draft_id)  # approved -> pending
        kr.KnowledgeRetriever.rebuild_seed_index()
        self.assertFalse(
            self.collections[kr.COLLECTION_NAMES["seed"]].get(ids=[did])["ids"],
            "recall 后重建应移除该草稿向量（Bug2 回归）",
        )
        self.assertEqual(
            len(self.collections[kr.COLLECTION_NAMES["seed"]].get(where={"source": "seed"})["ids"]),
            10,
            "recall 后种子应仍为 10 条",
        )

        # 再次批准 -> 重新入向量库
        KnowledgeDraft.approve(draft_id)
        kr.KnowledgeRetriever.rebuild_seed_index()
        self.assertTrue(
            self.collections[kr.COLLECTION_NAMES["seed"]].get(ids=[did])["ids"],
            "二次批准后应重新入向量库",
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
            self.collections[kr.COLLECTION_NAMES["seed"]].get(ids=[did])["ids"],
            "reject 后重建应移除该草稿向量（Bug2 回归）",
        )
        self.assertEqual(
            len(self.collections[kr.COLLECTION_NAMES["seed"]].get(where={"source": "seed"})["ids"]),
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

        # 数据形状对齐 _build_dim_query 当前约定（processes / network_connections /
        # webshell_items），确保三维检索至少一个维度有查询文本可命中
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
            "processes": [
                {"name": "Cobalt Strike", "cmd": "beacon.exe", "reason": "C2 beacon"},
            ],
            "network_connections": [
                {"remote_addr": "8.8.8.8", "protocol": "TCP"},
            ],
            "webshell_items": [
                {"path": "/tmp/shell.jsp", "funcs": ["eval"]},
            ],
        }

        results = kr.KnowledgeRetriever.retrieve(tiered, limit=5, structured=True)
        self.assertIsInstance(results, list)
        self.assertTrue(results, "向量检索应返回至少一条结构化结果")
        for item in results:
            self.assertIsInstance(item, dict)
            for key in ("title", "summary", "confidence", "score", "source"):
                self.assertIn(key, item)
            self.assertTrue(item.get("title"))

    # ── 7. 守卫：测试运行不触碰生产 data/chroma（A7 回归防护）────────
    def test_7_guard_production_chroma_untouched(self):
        """测试前后生产 `data/chroma` 的 ir_seed count 必须不变。

        A7 根因：原实现只 patch _get_collection，_build_seed_index/rebuild_seed_index
        直连持久化库，且 rebuild 先删后建 → 测试会清空生产索引。本用例读取生产
        持久化 ir_seed count，运行一次 rebuild（走 ephemeral mock），再比对 count。
        生产 chroma 不可读（未初始化/缺依赖）时跳过断言，避免误报。
        """
        import chromadb

        persist_dir = Path(kr.CHROMA_PERSIST_DIR)
        before_count = None
        try:
            client = chromadb.PersistentClient(
                path=str(persist_dir),
                settings=chromadb.Settings(anonymized_telemetry=False),
            )
            coll = client.get_collection(kr.COLLECTION_NAMES["seed"])
            before_count = coll.count()
        except Exception:
            # 生产向量库不存在或不可读 → 本次跳过（无法比对，但也不会被破坏）
            before_count = None

        # 以 mock（ephemeral）环境触发 rebuild，验证不写生产库
        kr.KnowledgeRetriever.rebuild_seed_index()
        self.assertGreaterEqual(
            self.collections[kr.COLLECTION_NAMES["seed"]].count(),
            10,
            "ephemeral seed collection 应有 10 条内置种子",
        )

        if before_count is None:
            return
        try:
            client = chromadb.PersistentClient(
                path=str(persist_dir),
                settings=chromadb.Settings(anonymized_telemetry=False),
            )
            after_count = client.get_collection(kr.COLLECTION_NAMES["seed"]).count()
        except Exception:
            return  # 生产库后续不可读 → 无法比对，跳过
        self.assertEqual(
            after_count, before_count,
            "测试不得改动生产 data/chroma 的 ir_seed（A7 破坏性副作用回归）",
        )

    # ── 8. rebuild 维度不符时不删除旧条目（A7 生产加固守卫）────────
    def test_8_rebuild_dim_mismatch_does_not_delete(self):
        """rebuild_seed_index 在 upsert 失败（维度不符）时不得删除任何旧条目。

        模拟：ephemeral seed collection 已含 1 条 384 维旧条目；随后把 embedding
        stub 维度改为 768 → upsert 抛 InvalidDimensionException → rebuild 应返回
        False 且旧条目仍存在（原「先删后建」实现会在失败前清空索引）。
        """

        class _Dim768Stub:
            """768 维确定性桩（与 384 维旧条目冲突）。"""

            DIM = 768

            def encode(self, texts, **kwargs):
                if isinstance(texts, str):
                    texts = [texts]
                arr = np.full((len(texts), self.DIM), 0.01, dtype=np.float32)
                return arr

        import chromadb
        import shutil

        # 独立临时目录 + PersistentClient（避开 setUp 已 patch 的 384 维 stub，
        # 且不共享 chromadb 进程级 System 单例）
        tmp_dir = tempfile.mkdtemp(prefix="qa_chroma_dim_")
        try:
            client = chromadb.PersistentClient(
                path=tmp_dir,
                settings=chromadb.Settings(anonymized_telemetry=False),
            )
            coll = client.get_or_create_collection(
                name="dim_mismatch_guard",
                metadata={"hnsw:space": "cosine"},
            )
            coll.add(
                ids=["seed_0_old"],
                embeddings=np.full((1, 384), 0.01, dtype=np.float32).tolist(),
                documents=["old entry"],
                metadatas=[{"source": "seed"}],
            )
            before = coll.count()
            self.assertEqual(before, 1)

            with mock.patch.object(
                kr, "_get_collection_by_name", return_value=coll
            ), mock.patch.object(
                kr, "_get_embedding_model", return_value=_Dim768Stub()
            ):
                ok = kr.KnowledgeRetriever.rebuild_seed_index()
            # upsert 抛维度异常 → 不执行 delete → 返回 False，旧条目保留
            self.assertFalse(ok, "维度不符时 rebuild 应失败")
            self.assertEqual(
                coll.count(), before,
                "维度不符时不得删除旧条目（A7 破坏性窗口回归）",
            )
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)


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
