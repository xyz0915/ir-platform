"""证据可点击溯源（knowledge_evidence -> 知识库详情）增量功能测试套件.

覆盖 T1-T6 新增契约：
  T1  后端 entry_ref / entry_type 透传
      - _derive_entry_type 前缀派生（seed/draft/rule/unknown）
      - _keyword_retrieve 三分支注入 entry_ref/entry_type（rule/seed/draft），
        C2 签名分支 entry_ref=None（不注入，前端降级纯文本）
      - _vector_retrieve 结构化项 entry_ref == chroma doc_id，entry_type 由前缀派生
  T2  后端草稿详情接口 GET /api/knowledge/drafts/{draft_id}
      - 存在 -> 200 且 data 含该草稿
      - 不存在 -> 404
      - 未鉴权 -> 401/403（与既有 8 个路由一致）
  T3-T5 纯前端（无单测框架），见文件底部 code review 结论，不阻塞。

Mock 策略（沿用 test_knowledge_retriever.py 既有写法）：
  - patch knowledge_retriever._get_embedding_model -> 384 维确定性 stub
  - patch knowledge_retriever._get_collection -> chromadb.Client() 内存库（ephemeral）
  - _keyword_retrieve 分支测试：patch _load_rules / _load_seed_data / _load_c2_signatures
    为受控数据，保证命中确定性
  - 显式置 _CHROMA_AVAILABLE=True / _EMBEDDING_AVAILABLE=True

运行方式（必须在 backend/ 目录下，使用项目 venv，避免系统 python 缺 bcrypt）:
    cd backend
    venv/Scripts/python -m pytest tests/test_evidence_trace.py -v
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import app.config as config  # noqa: E402
from app.services import knowledge_retriever as kr  # noqa: E402


class _StubEmbeddingModel:
    """确定性、不需联网下载的 embedding 桩（对齐 test_knowledge_retriever）。

    返回固定维度(384)向量；对所有输入返回相同常量向量 ->
    任意 query 与任意 doc 的 cosine distance = 0，向量检索必定命中。
    encode 同时支持单条字符串与字符串列表两种入参。
    """

    DIM = 384

    def encode(self, texts, **kwargs):
        if isinstance(texts, str):
            texts = [texts]
        arr = np.full((len(texts), self.DIM), 0.01, dtype=np.float32)
        return arr


# ============================================================================
# T1-a: _derive_entry_type 前缀派生单测
# ============================================================================

class TestDeriveEntryType(unittest.TestCase):
    """验证 entry_ref 前缀 -> entry_type 派生（与前端 parseEntryRef 双写一致）."""

    def test_seed_with_dot_subtechnique(self):
        # 关键边界：T1059.001 含点号无下划线
        self.assertEqual(kr._derive_entry_type("seed_0_T1059.001"), "seed")

    def test_pure_seed(self):
        self.assertEqual(kr._derive_entry_type("seed_4_T1071"), "seed")

    def test_draft(self):
        self.assertEqual(kr._derive_entry_type("draft_7"), "draft")

    def test_rule(self):
        self.assertEqual(kr._derive_entry_type("rule_3_T1059"), "rule")

    def test_none_is_unknown(self):
        self.assertEqual(kr._derive_entry_type(None), "unknown")

    def test_empty_string_is_unknown(self):
        self.assertEqual(kr._derive_entry_type(""), "unknown")

    def test_garble_is_unknown(self):
        # 非 seed_/draft_/rule_ 前缀 -> unknown（前端按不可点击纯文本降级）
        self.assertEqual(kr._derive_entry_type("xyz_123"), "unknown")
        self.assertEqual(kr._derive_entry_type("unknown_blob_9"), "unknown")


# ============================================================================
# T1-b: _keyword_retrieve 三分支 entry_ref/entry_type 注入
# ============================================================================

class TestKeywordRetrieveEntryRef(unittest.TestCase):
    """关键词回退路径下，entry_ref/entry_type 按分支正确注入且成对出现."""

    def setUp(self):
        # 重置模块级缓存，避免受其它测试污染
        kr._RULES_CACHE = []
        kr._C2_SIGNATURES_CACHE = []
        kr._SEED_CACHE = []

        self.patchers = []
        # 注意：必须捕获 start() 返回的 MagicMock，再对其设 return_value，
        # 否则 return_value 会被设到 patcher 对象上而无效（此前踩坑）。
        self.rules_patch = mock.patch.object(kr, "_load_rules", return_value=[])
        self.rules_mock = self.rules_patch.start()
        self.patchers.append(self.rules_patch)

        self.c2_patch = mock.patch.object(kr, "_load_c2_signatures", return_value=[])
        self.c2_mock = self.c2_patch.start()
        self.patchers.append(self.c2_patch)

        self.seeds_patch = mock.patch.object(kr, "_load_seed_data", return_value=[])
        self.seeds_mock = self.seeds_patch.start()
        self.patchers.append(self.seeds_patch)

    def tearDown(self):
        for p in self.patchers:
            p.stop()
        kr._RULES_CACHE = []
        kr._C2_SIGNATURES_CACHE = []
        kr._SEED_CACHE = []

    def _retrieve(self, analysis_data, limit=10):
        return kr.KnowledgeRetriever._keyword_retrieve(
            analysis_data, limit=limit, structured=True
        )

    def _assert_pairing(self, results):
        """entry_ref 与 entry_type 必须成对出现，且 entry_type 由 entry_ref 前缀派生."""
        self.assertTrue(results, "关键词回退未返回任何结构化结果")
        for item in results:
            has_ref = "entry_ref" in item
            has_type = "entry_type" in item
            self.assertEqual(
                has_ref, has_type,
                f"entry_ref/entry_type 未成对出现: {item}",
            )
            if has_ref:
                self.assertEqual(
                    item["entry_type"],
                    kr._derive_entry_type(item["entry_ref"]),
                    f"entry_type 与 entry_ref 前缀派生不一致: {item}",
                )

    # ── rule 分支：entry_ref = rule_{i}_{rule_name} ──
    def test_rule_branch_injects_rule_entry_ref(self):
        self.rules_mock.return_value = [{
            "name": "Cobalt Strike",
            "description": "cobalt strike beacon c2 framework",
            "category": "c2",
            "severity": "critical",
        }]
        analysis_data = {
            "host_basic": {"hostname": "WIN-TEST", "os_type": "Windows"},
            "analysis_result": {
                "risk_level": "critical",
                "summary": "Cobalt Strike beacon c2 framework detected",
            },
            "abnormal_processes_high": [
                {"name": "Cobalt Strike", "cmd": "beacon.exe -k", "reason": "c2 beacon"},
            ],
        }
        results = self._retrieve(analysis_data)
        self._assert_pairing(results)

        rule_items = [r for r in results if r.get("entry_type") == "rule"]
        self.assertTrue(rule_items, "rule 分支未产出结构化结果")
        for r in rule_items:
            # i 与 _build_index 同序（此处仅 1 条规则 -> i=0）
            self.assertEqual(r["entry_ref"], "rule_0_Cobalt Strike")
            self.assertTrue(r["entry_ref"].startswith("rule_"))

    # ── seed 分支（纯种子）：entry_ref = seed_{i}_{mitre_id} ──
    def test_seed_branch_injects_seed_entry_ref(self):
        self.seeds_mock.return_value = [{
            "id": "T1059.001",
            "name": "Command and Scripting Interpreter",
            "description": "powershell abuse abusing legitimate tools",
            "category": "execution",
            "severity": "high",
            "pattern": "powershell -enc",
        }]
        analysis_data = {
            "host_basic": {"hostname": "WIN", "os_type": "Windows"},
            "analysis_result": {
                "risk_level": "high",
                "summary": "powershell abuse command scripting interpreter",
            },
            "abnormal_processes_high": [
                {"name": "Command and Scripting Interpreter",
                 "cmd": "powershell -enc", "reason": "powershell abuse"},
            ],
        }
        results = self._retrieve(analysis_data)
        self._assert_pairing(results)

        seed_items = [r for r in results if r.get("entry_type") == "seed"]
        self.assertTrue(seed_items, "seed 分支未产出结构化结果")
        for r in seed_items:
            # i=0（前 10 条内置种子），mitre_id=T1059.001 含点号
            self.assertEqual(r["entry_ref"], "seed_0_T1059.001")
            self.assertTrue(r["entry_ref"].startswith("seed_"))

    # ── draft 分支（来自 get_as_seed_entries，id 形如 draft_<n>）──
    def test_draft_branch_injects_draft_entry_ref(self):
        self.seeds_mock.return_value = [{
            "id": "draft_7",
            "name": "Malicious Tool X",
            "description": "beacon malware behavior detected",
            "category": "malware",
            "severity": "high",
            "pattern": "beacon",
        }]
        analysis_data = {
            "host_basic": {"hostname": "WIN"},
            "analysis_result": {
                "risk_level": "high",
                "summary": "malicious tool x beacon malware behavior",
            },
            "abnormal_processes_high": [
                {"name": "Malicious Tool X", "cmd": "beacon.exe", "reason": "malware"},
            ],
        }
        results = self._retrieve(analysis_data)
        self._assert_pairing(results)

        draft_items = [r for r in results if r.get("entry_type") == "draft"]
        self.assertTrue(draft_items, "draft 分支未产出结构化结果")
        for r in draft_items:
            # draft 分支直接复用 seed["id"]，不与 _build_seed_index 的 i 关联
            self.assertEqual(r["entry_ref"], "draft_7")
            self.assertTrue(r["entry_ref"].startswith("draft_"))

    # ── C2 签名分支：entry_ref=None -> 不注入（前端降级纯文本）──
    def test_c2_branch_has_no_entry_ref(self):
        self.c2_mock.return_value = ["cobaltstrike"]
        analysis_data = {
            "abnormal_processes_high": [
                {"name": "Cobalt Strike", "cmd": "beacon cobaltstrike", "reason": "c2"},
            ],
        }
        results = self._retrieve(analysis_data)
        self.assertTrue(results, "C2 分支未产出结构化结果")
        for item in results:
            self.assertNotIn(
                "entry_ref", item,
                "C2 签名分支不应注入 entry_ref（应降级为不可点击纯文本）",
            )
            self.assertNotIn(
                "entry_type", item,
                "C2 签名分支不应注入 entry_type",
            )


# ============================================================================
# T1-c: _vector_retrieve 结构化项 entry_ref == chroma doc_id
# ============================================================================

class TestVectorRetrieveEntryRef(unittest.TestCase):
    """向量检索路径下，entry_ref 直接取 chroma 文档 ID，entry_type 由前缀派生."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        config.settings.DB_PATH = self.tmp.name
        from app.database import init_db
        init_db()

        kr._COLLECTION = None
        kr._EMBEDDING_MODEL = None
        kr._SEED_CACHE = []
        kr._SEED_INDEXED = False
        kr._CHROMA_AVAILABLE = True
        kr._EMBEDDING_AVAILABLE = True
        kr.KnowledgeRetriever._index_initialized = False

        import chromadb
        self.chroma_client = chromadb.Client()
        self.collection = self.chroma_client.get_or_create_collection(
            name=kr.COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )

        self.patchers = []
        p1 = mock.patch.object(kr, "_get_collection", return_value=self.collection)
        p1.start()
        self.patchers.append(p1)
        self.stub = _StubEmbeddingModel()
        p2 = mock.patch.object(kr, "_get_embedding_model", return_value=self.stub)
        p2.start()
        self.patchers.append(p2)

        # 仅注入 3 条受控规则，使集合规模可控（3 rules + 10 seeds + 1 draft = 14），
        # 避免「全部向量距离恒为 0、规则数远超 limit」导致 _vector_retrieve 提前
        # break 而从未处理到 seed/draft 文档（纯测试桩副作用，非源码缺陷）。
        p3 = mock.patch.object(kr, "_load_rules", return_value=[
            {"name": "Rule Alpha", "description": "alpha", "category": "cat", "severity": "high"},
            {"name": "Rule Beta", "description": "beta", "category": "cat", "severity": "medium"},
            {"name": "Rule Gamma", "description": "gamma", "category": "cat", "severity": "low"},
        ])
        p3.start()
        self.patchers.append(p3)

        # 创建一个已批准草稿，使向量库同时含 seed/rule/draft 三类 doc，
        # 以在同一检索结果中验证三种 entry_ref 形态。
        # 先建索引（rules + seeds），再批准草稿追加 draft_<id>，
        # 避免在 _build_index 前 collection 已含 draft_* 文档导致幂等早退。
        kr.KnowledgeRetriever._index_initialized = False
        kr.KnowledgeRetriever._ensure_index()

        from app.models.knowledge_draft import KnowledgeDraft
        draft = KnowledgeDraft.create(
            title="向量检索溯源草稿",
            description="用于验证 draft_<id> 进入向量库并被标记为 entry_type=draft",
            category="malware",
            severity="high",
            source="manual",
        )
        self.draft_id = draft["id"]
        KnowledgeDraft.approve(self.draft_id)
        kr.KnowledgeRetriever.rebuild_seed_index()

        self.doc_ids = set(self.collection.get()["ids"])

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

    def test_vector_results_carry_entry_ref_matching_doc_ids(self):
        analysis_data = {
            "host_basic": {"hostname": "WIN-VEC", "ip_address": "10.0.0.7", "os_type": "Windows"},
            "analysis_result": {"risk_level": "high", "summary": "Cobalt Strike powershell T1059"},
        }
        results = kr.KnowledgeRetriever._vector_retrieve(
            analysis_data, limit=50, collection=self.collection,
            model=self.stub, structured=True,
        )
        self.assertIsInstance(results, list)
        self.assertTrue(results, "向量检索应返回至少一条结构化结果")

        types_seen = set()
        for item in results:
            self.assertIn("entry_ref", item, "结构化结果缺少 entry_ref")
            self.assertIn("entry_type", item, "结构化结果缺少 entry_type")
            # 契约核心：向量分支 entry_ref == chroma 文档 ID 本身
            self.assertIn(
                item["entry_ref"], self.doc_ids,
                f"entry_ref 与 chroma 文档 ID 不一致: {item['entry_ref']}",
            )
            self.assertEqual(
                item["entry_type"], kr._derive_entry_type(item["entry_ref"]),
                "entry_type 与 entry_ref 前缀派生不一致",
            )
            types_seen.add(item["entry_type"])

        # 同一检索结果应覆盖三类来源（确保 seed / rule / draft 均被标记）
        self.assertIn("seed", types_seen, "向量结果未覆盖 seed 类 entry_ref")
        self.assertIn("rule", types_seen, "向量结果未覆盖 rule 类 entry_ref")
        self.assertIn("draft", types_seen, "向量结果未覆盖 draft 类 entry_ref")

    def test_vector_draft_entry_ref_format(self):
        # 直接校验已批准草稿的 chroma 文档 ID 形态为 draft_{numeric_id}
        self.assertIn(
            f"draft_{self.draft_id}", self.doc_ids,
            "已批准草稿应以 draft_<id> 形式进入向量库",
        )
        analysis_data = {
            "host_basic": {"hostname": "H", "os_type": "Windows"},
            "analysis_result": {"risk_level": "high", "summary": "malware behavior beacon"},
        }
        results = kr.KnowledgeRetriever._vector_retrieve(
            analysis_data, limit=50, collection=self.collection,
            model=self.stub, structured=True,
        )
        draft_refs = [r["entry_ref"] for r in results if r.get("entry_type") == "draft"]
        self.assertTrue(draft_refs, "未检索到 draft 类结构化结果")
        self.assertIn(f"draft_{self.draft_id}", draft_refs)


# ============================================================================
# T2: GET /api/knowledge/drafts/{draft_id} 路由鉴权与存在性
# ============================================================================

class TestDraftDetailRoute(unittest.TestCase):
    """新增草稿详情接口：存在->200 / 不存在->404 / 未鉴权->401."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        cls.tmp.close()
        config.settings.DB_PATH = cls.tmp.name

        from app.database import init_db
        init_db()

        from app.main import app
        from fastapi.testclient import TestClient
        from app.models.knowledge_draft import KnowledgeDraft

        cls.client = TestClient(app)
        resp = cls.client.post(
            "/api/auth/login", json={"username": "admin", "password": "admin123"}
        )
        assert resp.status_code == 200, f"登录失败: {resp.text}"
        cls.token = resp.json()["data"]["token"]
        cls.headers = {"Authorization": f"Bearer {cls.token}"}

        # 预置一条草稿，供「存在」用例使用
        cls.draft = KnowledgeDraft.create(
            title="QA 草稿详情",
            description="用于验证 GET /drafts/{id} 透传",
            category="auto",
            severity="low",
            source="manual",
        )

    @classmethod
    def tearDownClass(cls):
        try:
            os.unlink(cls.tmp.name)
        except OSError:
            pass

    def test_exists_returns_200_with_data(self):
        resp = self.client.get(
            f"/api/knowledge/drafts/{self.draft['id']}", headers=self.headers
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["code"], 0)
        self.assertEqual(body["data"]["id"], self.draft["id"])
        # 透传字段应包含关键列
        for key in ("title", "description", "status", "category", "severity"):
            self.assertIn(key, body["data"])

    def test_not_exists_returns_404(self):
        resp = self.client.get(
            "/api/knowledge/drafts/999999", headers=self.headers
        )
        self.assertEqual(resp.status_code, 404)

    def test_no_auth_returns_401(self):
        # 与既有 8 个路由一致：未带 token -> 401（FastAPI HTTPBearer 亦可能返回 403）
        resp = self.client.get(f"/api/knowledge/drafts/{self.draft['id']}")
        self.assertIn(resp.status_code, (401, 403))


if __name__ == "__main__":
    unittest.main(verbosity=2)
