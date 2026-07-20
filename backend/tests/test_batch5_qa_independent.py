"""第⑤批 P2-H 知识库自进化闭环 — 独立 QA 验证（严过关，不依赖工程师自测）.

覆盖范围（对照 team-lead 验证清单）：
1. 鉴权闸门：4 端点全部 Depends(get_current_user)；无 token → 401；
   端点解析于 /api/kb/...，且不与既有 /api/knowledge 路由冲突。
2. 反馈模型 / CRUD：提交、按类型/沉淀状态过滤列出、统计；
   feedback_type 枚举（false_positive/true_positive/suppress）为事实来源；
   kb_feedback 表 + 2 索引存在。
3. 自进化闭环：误报/抑制 → 写 rule_suppression（自动抑制）+ 生成 approved
   KnowledgeDraft + 回写 kb_feedback.applied_to_kb=true；反馈被标记为已沉淀。
4. 真阳性只沉淀不抑制：true_positive 走沉淀但不生成抑制规则。
5. LLM 降级：AgentLLM 无可用 Profile / 熔断/异常时，自进化仍以确定性方式完成闭环（不 500）。
6. 复用既有 KB：确认未另起平行 KB（沉淀落地到既有 knowledge_drafts 表，
   entry_ref='draft_<id>'，且触发既有 KnowledgeRetriever.rebuild_seed_index）。
7. 前端契约：后端响应字段与 KbFeedbackView.vue 消费字段一致；
   api/kbFeedback.js 路径与后端一致（由 router baseURL=/api 拼接）。
8. 回归保护：既有 /api/knowledge 知识库路由不受影响（冒烟 /api/knowledge/drafts 返回 200）。
9. 端到端冒烟：提交误报反馈 → evolve → 沉淀为 approved 草稿 + 抑制记录 → stats 体现沉淀数。

安全红线：
- 全部使用 IsolatedDBTestCase 临时 SQLite，绝不触碰 backend/data/ir_platform.db。
- 全部 LLM 调用经 FakeLLM/DegradedLLM/RaisingLLM mock，无外网、无超时。
- KnowledgeRetriever.rebuild_seed_index 以 mock 替代，绝不触碰 backend/data/chroma。
"""

import asyncio
import pathlib
import unittest
from unittest.mock import patch, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.knowledge import router as kb_router
from app.api.knowledge_draft import router as kd_router
from app.services.auth_service import get_current_user
from app.models.kb_feedback import (
    KbFeedback,
    VALID_FEEDBACK_TYPES,
    FEEDBACK_TYPE_FALSE_POSITIVE,
    FEEDBACK_TYPE_TRUE_POSITIVE,
    FEEDBACK_TYPE_SUPPRESS,
)
from app.models.knowledge_draft import KnowledgeDraft
from app.services.kb_self_evolve import KbSelfEvolve, DEPOSIT_SOURCE
from app.database import get_connection

from tests._qa_batch1_common import IsolatedDBTestCase


# ─────────────────────────────────────────────────────────────────────────────
# Fake / 降级 LLM（替代 AgentLLM，确定性、无副作用）
# ─────────────────────────────────────────────────────────────────────────────
class FakeLLM:
    """正常可用 LLM：返回确定性摘要。"""

    def __init__(self, *args, **kwargs):
        pass

    async def call(self, prompt, user=None, budget=None):
        return {
            "content": "FakeLLM 沉淀摘要：该规则命中为误报，应降低置信度并沉淀为知识。",
            "usage": {},
            "degraded": False,
            "error": None,
        }


class DegradedLLM:
    """无可用 Profile / 熔断：返回 degraded=True，触发确定性降级。"""

    def __init__(self, *args, **kwargs):
        pass

    async def call(self, prompt, user=None, budget=None):
        return {
            "content": "",
            "usage": {},
            "degraded": True,
            "error": "未配置有效的 AI Profile（请先在 AI 设置中激活配置）",
        }


class RaisingLLM:
    """模拟 LLM 调用抛异常（熔断 / 网络错误）：_gen_summary 应捕获并走确定性降级。"""

    def __init__(self, *args, **kwargs):
        pass

    async def call(self, prompt, user=None, budget=None):
        raise RuntimeError("circuit breaker open")


# ─────────────────────────────────────────────────────────────────────────────
# 测试辅助
# ─────────────────────────────────────────────────────────────────────────────
def _build_client(include_knowledge_draft=False):
    """构建一个只含 kb 路由（可选含 knowledge_draft 路由）的测试应用，并注入认证。"""
    app = FastAPI()
    app.include_router(kb_router, prefix="/api/kb")
    if include_knowledge_draft:
        app.include_router(kd_router, prefix="/api/knowledge")
    admin = {"id": 1, "username": "qa_admin", "role": "admin"}
    app.dependency_overrides[get_current_user] = lambda: admin
    return app, TestClient(app)


def _suppression_rows(rule_name):
    with get_connection() as conn:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM rule_suppression WHERE rule_name=?", (rule_name,)
            ).fetchall()
        ]


def _approved_drafts():
    return KnowledgeDraft.list_approved()


# ═════════════════════════════════════════════════════════════════════════════
# 1) 鉴权闸门 + 路由前缀（item 1）
# ═════════════════════════════════════════════════════════════════════════════
class TestKbAuthAndRouting(IsolatedDBTestCase):
    def test_auth_gate_all_endpoints_require_token(self):
        app, client = _build_client()
        app.dependency_overrides.clear()  # 还原真实鉴权
        cases = [
            ("post", "/api/kb/feedback", {"json": {"feedback_type": "false_positive"}}),
            ("get", "/api/kb/feedback", {}),
            ("post", "/api/kb/evolve", {"json": {}}),
            ("get", "/api/kb/stats", {}),
        ]
        for method, path, kw in cases:
            fn = getattr(client, method)
            r = fn(path, **kw)
            self.assertEqual(
                r.status_code, 401, f"{method.upper()} {path} 应 401，实际 {r.status_code}"
            )

    def test_routes_resolve_under_api_kb_prefix(self):
        app, client = _build_client()
        # FastAPI 0.139 将 include_router 的路由包装为 _IncludedRouter（app.routes 上无直接 path），
        # 改用 OpenAPI schema 提取真实已注册路径（含前缀）。
        paths = set(app.openapi()["paths"].keys())
        self.assertIn("/api/kb/feedback", paths)
        self.assertIn("/api/kb/evolve", paths)
        self.assertIn("/api/kb/stats", paths)

    def test_no_conflict_with_existing_knowledge_prefix(self):
        # 同时挂载 /api/kb 与既有 /api/knowledge，验证两者共存、路径不冲突
        # （若同 path+method 冲突，include_router 会直接抛异常，此处再于 schema 层校验无交集）
        app, client = _build_client(include_knowledge_draft=True)
        paths = set(app.openapi()["paths"].keys())
        self.assertIn("/api/kb/feedback", paths)
        self.assertIn("/api/knowledge/drafts", paths)
        kb_paths = {p for p in paths if p.startswith("/api/kb/")}
        kd_paths = {p for p in paths if p.startswith("/api/knowledge/")}
        self.assertFalse(kb_paths & kd_paths)


# ═════════════════════════════════════════════════════════════════════════════
# 2) 反馈模型 / CRUD（item 2）
# ═════════════════════════════════════════════════════════════════════════════
class TestKbFeedbackModelCRUD(IsolatedDBTestCase):
    def test_kb_feedback_table_and_two_indexes(self):
        with get_connection() as conn:
            tbl = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='kb_feedback'"
            ).fetchone()
            self.assertIsNotNone(tbl, "kb_feedback 表应存在")
            idx = [
                r["name"]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='kb_feedback'"
                ).fetchall()
            ]
            self.assertIn("idx_kb_feedback_type", idx)
            self.assertIn("idx_kb_feedback_applied", idx)
            self.assertEqual(len(idx), 2, f"应恰有 2 个索引，实际 {idx}")

    def test_create_three_types_enum_is_source_of_truth(self):
        for ft in VALID_FEEDBACK_TYPES:
            rec = KbFeedback.create(feedback_type=ft, rule_name="r_" + ft, content="x")
            self.assertEqual(rec["feedback_type"], ft)
        # is_false_positive 派生列：仅 false_positive 为真
        fp = KbFeedback.get_by_id(1)
        self.assertTrue(fp["is_false_positive"])
        tp = KbFeedback.get_by_id(2)
        self.assertFalse(tp["is_false_positive"])
        sp = KbFeedback.get_by_id(3)
        self.assertFalse(sp["is_false_positive"])

    def test_invalid_type_rejected_at_model(self):
        with self.assertRaises(ValueError):
            KbFeedback.create(feedback_type="bogus")

    def test_invalid_type_rejected_at_api_422(self):
        app, client = _build_client()
        r = client.post("/api/kb/feedback", json={"feedback_type": "bogus"})
        self.assertEqual(r.status_code, 422, r.text)

    def test_list_filter_by_feedback_type_and_applied(self):
        KbFeedback.create(feedback_type="false_positive", rule_name="a")
        KbFeedback.create(feedback_type="suppress", rule_name="b")
        KbFeedback.create(feedback_type="true_positive", rule_name="c")
        KbFeedback.mark_applied(1, kb_entry_id="draft_9")

        only_fp = KbFeedback.list(feedback_type="false_positive")
        self.assertEqual(only_fp["total"], 1)
        self.assertEqual(only_fp["items"][0]["feedback_type"], "false_positive")

        applied = KbFeedback.list(applied=1)
        self.assertEqual(applied["total"], 1)
        unapplied = KbFeedback.list(applied=0)
        self.assertEqual(unapplied["total"], 2)

    def test_list_unapplied_returns_only_unprocessed(self):
        KbFeedback.create(feedback_type="false_positive", rule_name="a")
        KbFeedback.create(feedback_type="suppress", rule_name="b")
        KbFeedback.mark_applied(1, kb_entry_id="draft_1")
        pending = KbFeedback.list_unapplied()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["id"], 2)

    def test_stats_counts_per_type_and_applied(self):
        KbFeedback.create(feedback_type="false_positive", rule_name="a")
        KbFeedback.create(feedback_type="false_positive", rule_name="b")
        KbFeedback.create(feedback_type="suppress", rule_name="c")
        KbFeedback.create(feedback_type="true_positive", rule_name="d")
        KbFeedback.mark_applied(1, kb_entry_id="draft_1")
        stats = KbFeedback.get_stats()
        self.assertEqual(stats["total"], 4)
        self.assertEqual(stats["false_positive"], 2)
        self.assertEqual(stats["suppress"], 1)
        self.assertEqual(stats["true_positive"], 1)
        self.assertEqual(stats["applied"], 1)
        self.assertEqual(stats["unapplied"], 3)


# ═════════════════════════════════════════════════════════════════════════════
# 3) 自进化闭环（误报/抑制 → 抑制 + 沉淀 + 标记）
# 4) 真阳性只沉淀不抑制
# 5) LLM 降级
# 6) 复用既有 KB
# ═════════════════════════════════════════════════════════════════════════════
class TestKbSelfEvolveLoop(IsolatedDBTestCase):
    @patch("app.services.kb_self_evolve.AgentLLM", FakeLLM)
    @patch("app.services.knowledge_retriever.KnowledgeRetriever.rebuild_seed_index")
    def test_false_positive_full_loop(self, mock_rebuild):
        fb = KbFeedback.create(
            feedback_type="false_positive",
            rule_name="rule_powershell",
            host_id=7,
            content="powershell 为运维常用，属误报",
        )
        svc = KbSelfEvolve()
        result = asyncio.run(svc.process_feedback(fb["id"]))

        # 闭环完成：沉淀标记 + 草稿 + 抑制
        self.assertTrue(result["applied_to_kb"])
        self.assertIsNotNone(result["knowledge_draft_id"])
        self.assertIsNotNone(result["suppression_id"])
        self.assertIsNotNone(result["entry_ref"])
        self.assertTrue(result["entry_ref"].startswith("draft_"))

        # 反馈被标记为已沉淀
        refreshed = KbFeedback.get_by_id(fb["id"])
        self.assertTrue(refreshed["applied_to_kb"])
        self.assertEqual(refreshed["kb_entry_id"], result["entry_ref"])
        self.assertEqual(refreshed["suppression_id"], result["suppression_id"])
        self.assertEqual(refreshed["knowledge_draft_id"], result["knowledge_draft_id"])

        # 沉淀为 approved 知识草稿（复用既有 knowledge_drafts）
        approved = _approved_drafts()
        self.assertEqual(len(approved), 1)
        self.assertEqual(approved[0]["id"], result["knowledge_draft_id"])
        self.assertEqual(approved[0]["source"], DEPOSIT_SOURCE)
        self.assertEqual(approved[0]["category"], "fp_lesson")

        # 抑制记录已写入（rule_suppression 既有表）
        rows = _suppression_rows("rule_powershell")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["host_id"], 7)

        # 复用既有 KB：触发了 rebuild_seed_index（best-effort 索引既有库）
        self.assertTrue(mock_rebuild.called)

    @patch("app.services.kb_self_evolve.AgentLLM", FakeLLM)
    @patch("app.services.knowledge_retriever.KnowledgeRetriever.rebuild_seed_index")
    def test_suppress_type_full_loop(self, mock_rebuild):
        fb = KbFeedback.create(feedback_type="suppress", rule_name="rule_scan", host_id=0)
        result = asyncio.run(KbSelfEvolve().process_feedback(fb["id"]))
        self.assertTrue(result["applied_to_kb"])
        self.assertIsNotNone(result["suppression_id"])
        rows = _suppression_rows("rule_scan")
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(_approved_drafts()), 1)

    @patch("app.services.kb_self_evolve.AgentLLM", FakeLLM)
    @patch("app.services.knowledge_retriever.KnowledgeRetriever.rebuild_seed_index")
    def test_true_positive_deposits_no_suppression(self, mock_rebuild):
        fb = KbFeedback.create(
            feedback_type="true_positive",
            rule_name="rule_ransom",
            content="确为真实勒索行为",
        )
        result = asyncio.run(KbSelfEvolve().process_feedback(fb["id"]))
        # 真阳性应沉淀
        self.assertTrue(result["applied_to_kb"])
        self.assertIsNotNone(result["knowledge_draft_id"])
        approved = _approved_drafts()
        self.assertEqual(len(approved), 1)
        self.assertEqual(approved[0]["category"], "tp_validation")
        # 但绝不生成抑制
        self.assertIsNone(result["suppression_id"])
        self.assertEqual(len(_suppression_rows("rule_ransom")), 0)

    @patch("app.services.kb_self_evolve.AgentLLM", FakeLLM)
    @patch("app.services.knowledge_retriever.KnowledgeRetriever.rebuild_seed_index")
    def test_evolve_all_marks_everything_applied(self, mock_rebuild):
        KbFeedback.create(feedback_type="false_positive", rule_name="r_a")
        KbFeedback.create(feedback_type="true_positive", rule_name="r_b")
        KbFeedback.create(feedback_type="suppress", rule_name="r_c")
        summary = asyncio.run(KbSelfEvolve().evolve_all())
        self.assertEqual(summary["processed"], 3)
        self.assertEqual(summary["applied"], 3)
        stats = KbSelfEvolve().stats()
        self.assertEqual(stats["applied"], 3)
        self.assertEqual(stats["unapplied"], 0)
        self.assertEqual(len(stats["deposits"]), 3)

    @patch("app.services.kb_self_evolve.AgentLLM", DegradedLLM)
    @patch("app.services.knowledge_retriever.KnowledgeRetriever.rebuild_seed_index")
    def test_llm_unavailable_degradation(self, mock_rebuild):
        fb = KbFeedback.create(feedback_type="false_positive", rule_name="rule_x")
        result = asyncio.run(KbSelfEvolve().process_feedback(fb["id"]))
        # LLM 不可用也要完成闭环（确定性降级摘要）
        self.assertTrue(result["applied_to_kb"])
        self.assertIsNotNone(result["knowledge_draft_id"])
        refreshed = KbFeedback.get_by_id(fb["id"])
        self.assertIn("经验沉淀", refreshed["summary"] or "")
        self.assertEqual(len(_approved_drafts()), 1)

    @patch("app.services.kb_self_evolve.AgentLLM", RaisingLLM)
    @patch("app.services.knowledge_retriever.KnowledgeRetriever.rebuild_seed_index")
    def test_llm_circuit_breaker_deterministic(self, mock_rebuild):
        # LLM 调用直接抛异常（熔断）→ 仍应确定性完成，不抛 500
        fb = KbFeedback.create(feedback_type="suppress", rule_name="rule_cb")
        result = asyncio.run(KbSelfEvolve().process_feedback(fb["id"]))
        self.assertTrue(result["applied_to_kb"])
        self.assertIsNotNone(result["knowledge_draft_id"])
        refreshed = KbFeedback.get_by_id(fb["id"])
        self.assertIn("经验沉淀", refreshed["summary"] or "")

    def test_no_parallel_kb_module_reuses_existing(self):
        # 静态：kb_self_evolve 复用既有 KnowledgeDraft / KnowledgeRetriever，未另起平行 KB 表
        src = pathlib.Path(__file__).resolve().parent.parent / "app" / "services" / "kb_self_evolve.py"
        content = src.read_text(encoding="utf-8")
        self.assertIn("KnowledgeDraft", content)
        self.assertIn("KnowledgeRetriever", content)
        # 不应出现平行沉淀表（如 kb_self_evolve_entries / kb_deposits）
        self.assertNotIn("kb_self_evolve_entries", content)
        self.assertNotIn("kb_deposits", content)


# ═════════════════════════════════════════════════════════════════════════════
# 8) 回归保护：既有 /api/knowledge 路由不受影响
# 9) 端到端冒烟（API 层）
# 1/5/7 API 层补充
# ═════════════════════════════════════════════════════════════════════════════
class TestKbApiEndpoints(IsolatedDBTestCase):
    def test_existing_knowledge_routes_unaffected(self):
        app, client = _build_client(include_knowledge_draft=True)
        # 既有知识库路由冒烟 → 200
        r = client.get("/api/knowledge/drafts")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["code"], 0)
        # 新 kb 路由同时可用
        r = client.get("/api/kb/feedback")
        self.assertEqual(r.status_code, 200)
        r = client.get("/api/kb/stats")
        self.assertEqual(r.status_code, 200)

    @patch("app.services.kb_self_evolve.AgentLLM", FakeLLM)
    @patch("app.services.knowledge_retriever.KnowledgeRetriever.rebuild_seed_index")
    def test_e2e_false_positive_smoke(self, mock_rebuild):
        app, client = _build_client()
        # 提交误报反馈
        r = client.post(
            "/api/kb/feedback",
            json={"feedback_type": "false_positive", "rule_name": "rule_e2e",
                  "host_id": 3, "content": "e2e 误报"},
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["code"], 0)
        fid = r.json()["data"]["feedback_id"]

        # 触发自进化（单条）
        r = client.post("/api/kb/evolve", json={"feedback_id": fid})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["data"]["applied"], 1)

        # 统计体现沉淀数
        r = client.get("/api/kb/stats")
        self.assertEqual(r.status_code, 200)
        d = r.json()["data"]
        self.assertEqual(d["applied"], 1)
        self.assertEqual(d["false_positive"], 1)
        self.assertEqual(len(d["deposits"]), 1)
        self.assertEqual(d["deposits"][0]["feedback_type"], "false_positive")
        self.assertTrue(d["deposits"][0]["kb_entry_id"].startswith("draft_"))

        # 直接 DB 证据：抑制记录 + approved 草稿
        self.assertEqual(len(_suppression_rows("rule_e2e")), 1)
        self.assertEqual(len(_approved_drafts()), 1)

    @patch("app.services.kb_self_evolve.AgentLLM", FakeLLM)
    @patch("app.services.knowledge_retriever.KnowledgeRetriever.rebuild_seed_index")
    def test_evolve_all_endpoint(self, mock_rebuild):
        app, client = _build_client()
        client.post("/api/kb/feedback", json={"feedback_type": "true_positive", "rule_name": "r1"})
        client.post("/api/kb/feedback", json={"feedback_type": "suppress", "rule_name": "r2", "host_id": 0})
        r = client.post("/api/kb/evolve", json={})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["data"]["processed"], 2)
        self.assertEqual(r.json()["data"]["applied"], 2)

    @patch("app.services.kb_self_evolve.AgentLLM", DegradedLLM)
    @patch("app.services.knowledge_retriever.KnowledgeRetriever.rebuild_seed_index")
    def test_evolve_endpoint_degraded_no_500(self, mock_rebuild):
        app, client = _build_client()
        client.post("/api/kb/feedback", json={"feedback_type": "false_positive", "rule_name": "r_deg", "content": "x"})
        r = client.post("/api/kb/evolve", json={})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["data"]["applied"], 1)

    @patch("app.services.kb_self_evolve.AgentLLM", FakeLLM)
    @patch("app.services.knowledge_retriever.KnowledgeRetriever.rebuild_seed_index")
    def test_evolve_nonexistent_feedback_404(self, mock_rebuild):
        app, client = _build_client()
        r = client.post("/api/kb/evolve", json={"feedback_id": 99999})
        self.assertEqual(r.status_code, 404, r.text)


# ═════════════════════════════════════════════════════════════════════════════
# 7) 前端契约：后端响应字段 = KbFeedbackView.vue 消费字段
# ═════════════════════════════════════════════════════════════════════════════
class TestKbFrontendContract(IsolatedDBTestCase):
    @patch("app.services.kb_self_evolve.AgentLLM", FakeLLM)
    @patch("app.services.knowledge_retriever.KnowledgeRetriever.rebuild_seed_index")
    def test_backend_response_contract_matches_vue(self, mock_rebuild):
        app, client = _build_client()
        # 三种类型各造一条并全部自进化，使 stats.deposits 有内容
        for ft, rn in [("false_positive", "r_fp"), ("true_positive", "r_tp"), ("suppress", "r_sp")]:
            client.post("/api/kb/feedback", json={"feedback_type": ft, "rule_name": rn, "content": "c"})
        client.post("/api/kb/evolve", json={})

        stats = client.get("/api/kb/stats").json()["data"]
        # stats 卡片 + 沉淀表消费字段
        for k in ("total", "applied", "unapplied", "false_positive", "suppress", "true_positive", "deposits"):
            self.assertIn(k, stats, f"stats 缺少字段 {k}（前端统计卡片依赖）")
        for dep in stats["deposits"]:
            for f in ("feedback_type", "rule_name", "kb_entry_id", "summary", "created_at"):
                self.assertIn(f, dep, f"deposits 缺少字段 {f}（前端沉淀表依赖）")

        lst = client.get("/api/kb/feedback").json()["data"]
        self.assertIn("items", lst)
        self.assertIn("total", lst)
        for item in lst["items"]:
            for f in ("feedback_type", "rule_name", "content", "source_user",
                      "applied_to_kb", "kb_entry_id", "created_at"):
                self.assertIn(f, item, f"feedback 列表缺少字段 {f}（前端反馈表依赖）")

    def test_frontend_api_paths_match_backend(self):
        # api/kbFeedback.js 使用 request baseURL=/api，url 为 /kb/... → 实际 /api/kb/...
        api_file = (
            pathlib.Path(__file__).resolve().parent.parent.parent
            / "frontend" / "src" / "api" / "kbFeedback.js"
        )
        self.assertTrue(api_file.exists(), "前端 api/kbFeedback.js 应存在")
        text = api_file.read_text(encoding="utf-8")
        self.assertIn("'/kb/feedback'", text)
        self.assertIn("'/kb/evolve'", text)
        self.assertIn("'/kb/stats'", text)


if __name__ == "__main__":
    unittest.main()
