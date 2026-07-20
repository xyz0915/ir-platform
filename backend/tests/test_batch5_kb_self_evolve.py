"""第⑤批 P2-H 隔离自测 — 知识库自进化闭环（误报 → 抑制 → 沉淀）.

安全红线：
- 使用 ``IsolatedDBTestCase``（临时 SQLite），**绝不触碰 backend/data/ir.db**。
- 全部 LLM 调用经 ``FakeLLM`` mock，无外网、无超时，稳定可重复。
- ``KnowledgeRetriever.rebuild_seed_index`` 以 no-op mock 替代，避免触碰 backend/data/chroma。
"""

import asyncio
import json
import unittest
from unittest.mock import patch

from app.models.kb_feedback import KbFeedback
from app.models.knowledge_draft import KnowledgeDraft
from app.services.kb_self_evolve import KbSelfEvolve
from app.database import get_connection

from tests._qa_batch1_common import IsolatedDBTestCase


# ── Fake LLM（确定性返回摘要 / 或降级）──────────────────────────────────
class FakeLLM:
    """替代 AgentLLM：同步无副作用，返回确定性的沉淀摘要."""

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
    """模拟 LLM 不可用（无 Profile / 熔断）：返回 degraded=True，触发确定性降级."""

    def __init__(self, *args, **kwargs):
        pass

    async def call(self, prompt, user=None, budget=None):
        return {
            "content": "",
            "usage": {},
            "degraded": True,
            "error": "未配置有效的 AI Profile（请先在 AI 设置中激活配置）",
        }


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


class TestKbFeedbackModel(IsolatedDBTestCase):
    """模型层：创建 / 列出 / 过滤 / 非法类型校验."""

    def test_create_and_list(self):
        KbFeedback.create(
            feedback_type="false_positive",
            rule_name="rule_powershell",
            content="这是误报",
            source_user="alice",
        )
        res = KbFeedback.list()
        self.assertEqual(res["total"], 1)
        self.assertEqual(res["items"][0]["feedback_type"], "false_positive")
        self.assertEqual(res["items"][0]["source_user"], "alice")
        self.assertFalse(res["items"][0]["applied_to_kb"])

    def test_list_filter_by_applied(self):
        KbFeedback.create(feedback_type="false_positive", rule_name="r1")
        KbFeedback.create(feedback_type="true_positive", rule_name="r2")
        KbFeedback.mark_applied(1, kb_entry_id="draft_9")
        unapplied = KbFeedback.list(applied=0)
        self.assertEqual(unapplied["total"], 1)
        applied = KbFeedback.list(applied=1)
        self.assertEqual(applied["total"], 1)

    def test_invalid_type_rejected(self):
        with self.assertRaises(ValueError):
            KbFeedback.create(feedback_type="bogus")


class TestKbSelfEvolveService(IsolatedDBTestCase):
    """服务层：误报沉淀进 KB、抑制闭环、真阳性不抑制、LLM 降级、批量自进化."""

    @patch("app.services.kb_self_evolve.AgentLLM", FakeLLM)
    @patch("app.services.knowledge_retriever.KnowledgeRetriever.rebuild_seed_index", return_value=True)
    def test_false_positive_deposits_to_kb(self, _mock_rebuild):
        fb = KbFeedback.create(
            feedback_type="false_positive",
            rule_name="rule_powershell",
            host_id=7,
            content="powershell 为运维常用，属误报",
        )
        svc = KbSelfEvolve()
        result = asyncio.run(svc.process_feedback(fb["id"]))
        self.assertTrue(result["applied_to_kb"])
        self.assertIsNotNone(result["knowledge_draft_id"])
        self.assertIsNotNone(result["suppression_id"])
        # 反馈被标记为已沉淀
        refreshed = KbFeedback.get_by_id(fb["id"])
        self.assertTrue(refreshed["applied_to_kb"])
        self.assertEqual(refreshed["kb_entry_id"], result["entry_ref"])
        # 知识草稿已 approved
        self.assertEqual(len(_approved_drafts()), 1)
        # 抑制记录已写入
        rows = _suppression_rows("rule_powershell")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["host_id"], 7)

    @patch("app.services.kb_self_evolve.AgentLLM", FakeLLM)
    @patch("app.services.knowledge_retriever.KnowledgeRetriever.rebuild_seed_index", return_value=True)
    def test_suppress_loop(self, _mock_rebuild):
        fb = KbFeedback.create(feedback_type="suppress", rule_name="rule_scan", host_id=0)
        result = asyncio.run(KbSelfEvolve().process_feedback(fb["id"]))
        self.assertTrue(result["applied_to_kb"])
        self.assertIsNotNone(result["suppression_id"])
        rows = _suppression_rows("rule_scan")
        self.assertEqual(len(rows), 1)

    @patch("app.services.kb_self_evolve.AgentLLM", FakeLLM)
    @patch("app.services.knowledge_retriever.KnowledgeRetriever.rebuild_seed_index", return_value=True)
    def test_true_positive_deposits_no_suppression(self, _mock_rebuild):
        fb = KbFeedback.create(
            feedback_type="true_positive",
            rule_name="rule_ransom",
            content="确为真实勒索行为",
        )
        result = asyncio.run(KbSelfEvolve().process_feedback(fb["id"]))
        self.assertTrue(result["applied_to_kb"])
        # 真阳性不应生成抑制
        self.assertIsNone(result["suppression_id"])
        self.assertEqual(len(_suppression_rows("rule_ransom")), 0)
        # 但应沉淀知识
        self.assertEqual(len(_approved_drafts()), 1)

    @patch("app.services.kb_self_evolve.AgentLLM", DegradedLLM)
    @patch("app.services.knowledge_retriever.KnowledgeRetriever.rebuild_seed_index", return_value=True)
    def test_llm_unavailable_degradation(self, _mock_rebuild):
        fb = KbFeedback.create(feedback_type="false_positive", rule_name="rule_x")
        result = asyncio.run(KbSelfEvolve().process_feedback(fb["id"]))
        # LLM 不可用也要完成闭环（确定性降级摘要）
        self.assertTrue(result["applied_to_kb"])
        self.assertIsNotNone(result["knowledge_draft_id"])
        refreshed = KbFeedback.get_by_id(fb["id"])
        self.assertIn("经验沉淀", refreshed["summary"] or "")

    @patch("app.services.kb_self_evolve.AgentLLM", FakeLLM)
    @patch("app.services.knowledge_retriever.KnowledgeRetriever.rebuild_seed_index", return_value=True)
    def test_evolve_all(self, _mock_rebuild):
        KbFeedback.create(feedback_type="false_positive", rule_name="r_a")
        KbFeedback.create(feedback_type="true_positive", rule_name="r_b")
        KbFeedback.create(feedback_type="suppress", rule_name="r_c")
        summary = asyncio.run(KbSelfEvolve().evolve_all())
        self.assertEqual(summary["processed"], 3)
        self.assertEqual(summary["applied"], 3)
        # 统计正确
        stats = KbSelfEvolve().stats()
        self.assertEqual(stats["applied"], 3)
        self.assertEqual(stats["unapplied"], 0)
        self.assertEqual(len(stats["deposits"]), 3)


class TestKbFeedbackAPI(IsolatedDBTestCase):
    """端到端 API：提交 / 列出 / 自进化 / 统计 / 鉴权闸门 / 非法类型."""

    def setUp(self):
        super().setUp()
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.api.knowledge import router
        from app.services.auth_service import get_current_user

        self.app = FastAPI()
        self.app.include_router(router, prefix="/api/kb")
        self.admin = {"user_id": 1, "username": "admin", "role": "admin"}
        self.app.dependency_overrides[get_current_user] = lambda: self.admin
        self.client = TestClient(self.app)
        self._get_current_user = get_current_user

    @patch("app.services.kb_self_evolve.AgentLLM", FakeLLM)
    @patch("app.services.knowledge_retriever.KnowledgeRetriever.rebuild_seed_index", return_value=True)
    def test_submit_list_evolve_stats(self, _mock_rebuild):
        # 提交
        r = self.client.post(
            "/api/kb/feedback",
            json={"feedback_type": "false_positive", "rule_name": "rule_powershell",
                  "host_id": 7, "content": "误报"},
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["code"], 0)
        fid = r.json()["data"]["feedback_id"]

        # 列出
        r = self.client.get("/api/kb/feedback")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["data"]["total"], 1)

        # 触发自进化
        r = self.client.post("/api/kb/evolve", json={"feedback_id": fid})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["data"]["applied"], 1)

        # 统计
        r = self.client.get("/api/kb/stats")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["data"]["applied"], 1)
        self.assertEqual(len(r.json()["data"]["deposits"]), 1)

    @patch("app.services.kb_self_evolve.AgentLLM", FakeLLM)
    @patch("app.services.knowledge_retriever.KnowledgeRetriever.rebuild_seed_index", return_value=True)
    def test_evolve_all_endpoint(self, _mock_rebuild):
        self.client.post("/api/kb/feedback", json={"feedback_type": "true_positive", "rule_name": "r1"})
        self.client.post("/api/kb/feedback", json={"feedback_type": "suppress", "rule_name": "r2", "host_id": 0})
        r = self.client.post("/api/kb/evolve", json={})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["data"]["processed"], 2)
        self.assertEqual(r.json()["data"]["applied"], 2)

    def test_auth_required(self):
        # 无 token -> 401
        self.app.dependency_overrides.clear()
        r = self.client.post("/api/kb/feedback", json={"feedback_type": "false_positive"})
        self.assertEqual(r.status_code, 401)
        r = self.client.get("/api/kb/feedback")
        self.assertEqual(r.status_code, 401)
        r = self.client.post("/api/kb/evolve", json={})
        self.assertEqual(r.status_code, 401)
        r = self.client.get("/api/kb/stats")
        self.assertEqual(r.status_code, 401)

    def test_invalid_type_422(self):
        r = self.client.post("/api/kb/feedback", json={"feedback_type": "bogus"})
        self.assertEqual(r.status_code, 422, r.text)


if __name__ == "__main__":
    unittest.main()
