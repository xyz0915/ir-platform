"""第④批 P0-B 隔离自测 — 规则自生成 + 影子运行 + 自动调优 + 人审启用.

安全红线：
- 使用 ``IsolatedDBTestCase``（临时 SQLite），**绝不触碰 backend/data/ir.db**。
- 全部 LLM 调用经 ``FakeLLM`` mock，无外网、无超时，稳定可重复。
"""

import asyncio
import json
import unittest
from unittest.mock import patch

from app.services.rule_dsl import RuleDSL
from app.services.rule_generator import RuleGenerator
from app.services.rule_shadow import RuleShadow
from app.services.rule_tuner import RuleTuner
from app.models.rule_draft import RuleDraft
from app.rules.rule_engine import RuleEngine
from app.database import get_connection

from tests._qa_batch1_common import IsolatedDBTestCase


# ── Fake LLM（确定性返回，覆盖生成 / 调优两条路径）──────────────────────
GENERATED = {
    "name": "ai_suspicious_powershell",
    "rule_type": "list",
    "condition": {"field": "process_name", "values": ["powershell.exe"], "match_mode": "exact"},
    "severity": "high",
    "label": "AI: 可疑 powershell 执行",
    "rationale": "样本中 powershell 频繁出现",
    "expected_fields": ["process_name"],
    "confidence": 0.8,
}
TUNED = {
    "rule_type": "list",
    "condition": {"field": "process_name", "values": ["powershell.exe"], "match_mode": "exact"},
    "severity": "medium",
    "label": "AI: 可疑 powershell 执行(调优)",
    "rationale": "据误报反馈降低严重度",
    "expected_fields": ["process_name"],
    "confidence": 0.85,
}


class FakeLLM:
    """替代 AgentLLM：同步无副作用，按提示词返回生成/调优结果."""

    def __init__(self, *args, **kwargs):
        pass

    async def call(self, prompt, user=None, budget=None):
        if "调优" in prompt:
            return {"content": json.dumps(TUNED), "usage": {}, "degraded": False, "error": None}
        return {"content": json.dumps(GENERATED), "usage": {}, "degraded": False, "error": None}


SAMPLE_LOGS = [
    {"event_type": "process_create", "process_name": "powershell.exe", "severity": "high",
     "timestamp": "2026-07-18 10:00:00"},
    {"event_type": "process_create", "process_name": "cmd.exe", "severity": "low",
     "timestamp": "2026-07-18 10:01:00"},
    {"event_type": "login", "process_name": "powershell.exe", "severity": "medium",
     "timestamp": "2026-07-18 10:02:00"},
]


class TestRuleDSL(IsolatedDBTestCase):
    """DSL 安全校验：可计算性 / 全表扫描 / 代码注入 / DDL / 笛卡尔积."""

    def test_valid_list_rule_passes(self):
        ok, err = RuleDSL.validate(
            "list", {"field": "process_name", "values": ["a.exe"], "match_mode": "exact"}
        )
        self.assertTrue(ok, err)

    def test_reject_full_scan_regex(self):
        ok, err = RuleDSL.validate("regex", {"pattern": ".*"})
        self.assertFalse(ok)
        self.assertIn("全表扫描", err)

    def test_reject_eval_injection(self):
        ok, err = RuleDSL.validate(
            "list", {"field": "process_name", "values": ["__import__('os')"], "match_mode": "exact"}
        )
        self.assertFalse(ok)

    def test_reject_ddl_injection(self):
        ok, err = RuleDSL.validate(
            "list",
            {"field": "process_name", "values": ["x'; DROP TABLE rules; --"], "match_mode": "exact"},
        )
        self.assertFalse(ok)

    def test_reject_huge_list(self):
        ok, err = RuleDSL.validate(
            "list", {"field": "process_name", "values": ["v"] * 2000, "match_mode": "exact"}
        )
        self.assertFalse(ok)

    def test_reject_non_whitelist_field(self):
        ok, err = RuleDSL.validate(
            "list", {"field": "secret_column", "values": ["x"], "match_mode": "exact"}
        )
        self.assertFalse(ok)


class TestRuleGenerationAndShadow(IsolatedDBTestCase):
    """生成 -> 影子运行：仅计数、绝不产生告警，且计数正确回写."""

    def setUp(self):
        super().setUp()
        self.seed_normalized_logs(SAMPLE_LOGS)

    def _load_logs(self):
        with get_connection() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM normalized_logs").fetchall()]

    @patch("app.services.rule_generator.AgentLLM", FakeLLM)
    def test_generate_and_shadow(self):
        gen = RuleGenerator()
        draft = asyncio.run(gen.generate(self._load_logs(), category="process"))
        self.assertEqual(draft["rule_type"], "list")
        ok, err = RuleDSL.validate(draft["rule_type"], draft["condition"])
        self.assertTrue(ok, err)

        obj = RuleDraft.create(
            name="ai_test_draft",
            rule_type=draft["rule_type"],
            condition=draft["condition"],
            severity=draft["severity"],
            label=draft["label"],
        )

        stats = RuleShadow.run_shadow(obj["id"])
        self.assertEqual(stats["hit_count"], 2)  # 两条 powershell.exe

        # 影子模式不产生告警：引擎对 is_shadow 规则不返回任何 match
        shadow_rule = {
            "name": obj["name"],
            "rule_type": obj["rule_type"],
            "condition": obj["condition"],
            "severity": obj["severity"],
            "is_shadow": True,
            "shadow_hit_count": 0,
        }
        matches = RuleEngine.evaluate(self._load_logs(), [shadow_rule])
        self.assertEqual(len(matches), 0, "影子规则不应产生告警")

        # 草稿状态与命中数正确回写
        updated = RuleDraft.get_by_id(obj["id"])
        self.assertEqual(updated["status"], RuleDraft.STATUS_SHADOW)
        self.assertEqual(updated["shadow_hit_count"], 2)

        # rules 镜像行存在且 is_shadow=1，shadow_hit_count 同步
        with get_connection() as conn:
            row = conn.execute(
                "SELECT is_shadow, shadow_hit_count FROM rules WHERE name = ?", (obj["name"],)
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["is_shadow"], 1)
        self.assertEqual(row["shadow_hit_count"], 2)

    @patch("app.services.rule_generator.AgentLLM", FakeLLM)
    def test_shadow_on_non_matching_returns_zero(self):
        # 用一条不会命中的条件做影子运行
        obj = RuleDraft.create(
            name="ai_no_match",
            rule_type="list",
            condition={"field": "process_name", "values": ["never_existing_bin"], "match_mode": "exact"},
            severity="low",
        )
        stats = RuleShadow.run_shadow(obj["id"])
        self.assertEqual(stats["hit_count"], 0)
        self.assertEqual(RuleDraft.get_by_id(obj["id"])["status"], RuleDraft.STATUS_SHADOW)


class TestRuleTuner(IsolatedDBTestCase):
    """自动调优：生成新版本草稿，原草稿进入待复审."""

    @patch("app.services.rule_generator.AgentLLM", FakeLLM)
    @patch("app.services.rule_tuner.AgentLLM", FakeLLM)
    def test_tune_creates_new_version_and_marks_pending(self):
        parent = RuleDraft.create(
            name="ai_base",
            rule_type="list",
            condition={"field": "process_name", "values": ["powershell.exe"], "match_mode": "exact"},
            severity="high",
            label="base",
        )
        tuner = RuleTuner()
        new = asyncio.run(
            tuner.tune(
                parent,
                false_positive_examples=[{"process_name": "powershell.exe"}],
                feedback="疑似误报",
            )
        )
        self.assertNotEqual(new["name"], parent["name"])
        self.assertEqual(new["tuned_version"], 1)
        self.assertEqual(new["parent_draft_id"], parent["id"])
        # 原草稿进入待复审
        refreshed = RuleDraft.get_by_id(parent["id"])
        self.assertEqual(refreshed["status"], RuleDraft.STATUS_PENDING_REVIEW)


class TestRuleDraftAPI(IsolatedDBTestCase):
    """端到端 API：生成 -> 列表 -> 影子运行 -> 统计 -> 调优 -> 启用（admin）/ 驳回（admin）."""

    def setUp(self):
        super().setUp()
        self.seed_normalized_logs(SAMPLE_LOGS)
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.api.rules import router
        from app.services.auth_service import get_current_user

        self.app = FastAPI()
        self.app.include_router(router, prefix="/api/rules")
        self.admin = {"user_id": 1, "username": "admin", "role": "admin"}
        self.operator = {"user_id": 2, "username": "op", "role": "operator"}
        self.app.dependency_overrides[get_current_user] = lambda: self.admin
        self.client = TestClient(self.app)
        self._get_current_user = get_current_user

    @patch("app.services.rule_generator.AgentLLM", FakeLLM)
    def test_generate_and_full_flow(self):
        # 生成
        r = self.client.post("/api/rules/generate", json={})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["code"], 0)
        drafts = r.json()["data"]["drafts"]
        self.assertTrue(len(drafts) >= 1)
        did = drafts[0]["id"]

        # 列表
        r = self.client.get("/api/rules/drafts")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["code"], 0)

        # 影子运行
        r = self.client.post(f"/api/rules/drafts/{did}/shadow")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["data"]["hit_count"], 2)

        # 影子统计
        r = self.client.get(f"/api/rules/drafts/{did}/shadow-stats")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["data"]["hit_count"], 2)

        # 调优
        r = self.client.post(f"/api/rules/drafts/{did}/tune", json={"false_positive_examples": []})
        self.assertEqual(r.status_code, 200, r.text)

        # 启用（admin）
        r = self.client.post(f"/api/rules/drafts/{did}/enable")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["data"]["enabled"])

        # 启用后草稿状态应为 enabled
        r = self.client.get(f"/api/rules/drafts/{did}/shadow-stats")
        self.assertEqual(r.json()["data"]["status"], "enabled")

    @patch("app.services.rule_generator.AgentLLM", FakeLLM)
    def test_reject_flow_admin_only(self):
        r = self.client.post("/api/rules/generate", json={})
        did = r.json()["data"]["drafts"][0]["id"]
        # 驳回（admin）
        r = self.client.post(f"/api/rules/drafts/{did}/reject", json={"reason": "测试驳回"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["data"]["status"], "rejected")

    def test_auth_required_and_admin_only(self):
        # 无 token -> 401
        self.app.dependency_overrides.clear()
        r = self.client.post("/api/rules/drafts/999/shadow")
        self.assertEqual(r.status_code, 401)

        # operator 不能启用
        self.app.dependency_overrides[self._get_current_user] = lambda: self.operator
        d = RuleDraft.create(
            name="ai_auth",
            rule_type="list",
            condition={"field": "process_name", "values": ["x.exe"], "match_mode": "exact"},
        )
        r = self.client.post(f"/api/rules/drafts/{d['id']}/enable")
        self.assertEqual(r.status_code, 403)

        # operator 不能驳回
        r = self.client.post(f"/api/rules/drafts/{d['id']}/reject", json={})
        self.assertEqual(r.status_code, 403)


if __name__ == "__main__":
    unittest.main()
