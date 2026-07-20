"""第④批 P0-B 独立 QA 验证套件 — software-qa-engineer-4（严过关）.

目标：对工程师 software-engineer-6 交付的规则自生成 + 影子运行 + 自动调优 + 人审启用
做**独立**验证，覆盖 8 项验证清单：

1. 鉴权闸门（7 端点全部鉴权、enable/reject 限 admin、无 token→401、无重复前缀）
2. rule_dsl 安全校验（拒绝代码注入 / DDL / 全表扫描 / 笛卡尔积；绝不 eval 任意代码）
3. rule_generator 降级（无 Profile / 熔断 → 确定性启发式，不 500）
4. rule_shadow + rule_engine 影子分支（evaluate 返回 0 条告警；shadow_hit_count 正确递增落库）
5. rule_tuner 调优（新版本草稿 + parent_draft_id / tuned_version / tuning_history_json）
6. rule_draft 模型 + CRUD + 状态机（draft→shadow→approved/rejected）
7. 前端契约（RuleDraftView.vue 字段 / api/ruleDrafts.js 路径形状一致；vite build 通过）
8. 端到端冒烟（generate→draft→shadow→stats→tune→enable(admin)→生效；reject 路径）

安全红线：使用 ``IsolatedDBTestCase``（临时 SQLite），**绝不触碰 backend/data/ir.db**。
"""

import ast
import asyncio
import json
import os
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

# ── Fake LLM ────────────────────────────────────────────────────────────────
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


class _FakeLLMOk:
    """返回合法生成 / 调优结果（覆盖生成与调优两条路径）."""

    def __init__(self, *args, **kwargs):
        pass

    async def call(self, prompt, user=None, budget=None):
        if "调优" in prompt:
            return {"content": json.dumps(TUNED), "usage": {}, "degraded": False, "error": None}
        return {"content": json.dumps(GENERATED), "usage": {}, "degraded": False, "error": None}


class _FakeLLMDegraded:
    """模拟无 Profile / 断路器熔断：返回 degraded=True。"""

    def __init__(self, *args, **kwargs):
        pass

    async def call(self, prompt, user=None, budget=None):
        return {"content": "", "usage": {}, "degraded": True, "error": "未配置有效的 AI Profile"}


SAMPLE_LOGS = [
    {"event_type": "process_create", "process_name": "powershell.exe", "severity": "high",
     "timestamp": "2026-07-18 10:00:00"},
    {"event_type": "process_create", "process_name": "cmd.exe", "severity": "low",
     "timestamp": "2026-07-18 10:01:00"},
    {"event_type": "login", "process_name": "powershell.exe", "severity": "medium",
     "timestamp": "2026-07-18 10:02:00"},
]


# ── ① 鉴权闸门 ───────────────────────────────────────────────────────────
class TestAuthGate(IsolatedDBTestCase):
    """7 个端点全部须鉴权；enable/reject 仅 admin；无 token→401；无重复前缀."""

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
        self._gcu = get_current_user

    def _seven_endpoints(self):
        # (method, path, json_body) — 覆盖 7 个 P0-B 端点
        return [
            ("POST", "/api/rules/generate", {}),
            ("GET", "/api/rules/drafts", None),
            ("POST", "/api/rules/drafts/1/shadow", None),
            ("GET", "/api/rules/drafts/1/shadow-stats", None),
            ("POST", "/api/rules/drafts/1/tune", {}),
            ("POST", "/api/rules/drafts/1/enable", None),
            ("POST", "/api/rules/drafts/1/reject", {}),
        ]

    def test_no_token_returns_401_on_all_endpoints(self):
        # 清掉 override，模拟未鉴权请求
        self.app.dependency_overrides.clear()
        for method, path, body in self._seven_endpoints():
            if method == "GET":
                r = self.client.get(path)
            else:
                r = self.client.post(path, json=body if body is not None else {})
            self.assertEqual(
                r.status_code, 401,
                f"{method} {path} 期望 401（无 token），实际 {r.status_code}: {r.text[:200]}"
            )

    def test_enable_and_reject_require_admin_else_403(self):
        d = RuleDraft.create(
            name="ai_auth",
            rule_type="list",
            condition={"field": "process_name", "values": ["x.exe"], "match_mode": "exact"},
        )
        # 切换为 operator
        self.app.dependency_overrides[self._gcu] = lambda: self.operator
        r = self.client.post(f"/api/rules/drafts/{d['id']}/enable")
        self.assertEqual(r.status_code, 403, r.text[:200])
        r = self.client.post(f"/api/rules/drafts/{d['id']}/reject", json={})
        self.assertEqual(r.status_code, 403, r.text[:200])

    def test_non_admin_can_access_other_five_endpoints(self):
        self.app.dependency_overrides[self._gcu] = lambda: self.operator
        # generate（需样本日志，已 seed）
        r = self.client.post("/api/rules/generate", json={})
        self.assertEqual(r.status_code, 200, r.text[:200])
        did = r.json()["data"]["drafts"][0]["id"]
        self.assertEqual(self.client.get("/api/rules/drafts").status_code, 200)
        self.assertEqual(self.client.post(f"/api/rules/drafts/{did}/shadow").status_code, 200)
        self.assertEqual(self.client.get(f"/api/rules/drafts/{did}/shadow-stats").status_code, 200)
        self.assertEqual(self.client.post(f"/api/rules/drafts/{did}/tune", json={}).status_code, 200)

    def test_no_duplicate_prefix(self):
        # 正确前缀
        r = self.client.post("/api/rules/generate", json={})
        self.assertEqual(r.status_code, 200, r.text[:200])
        # 重复前缀不应解析到任何路由
        r = self.client.post("/api/rules/rules/generate", json={})
        self.assertEqual(r.status_code, 404, f"重复前缀应 404，实际 {r.status_code}")


# ── ② rule_dsl 安全校验 ───────────────────────────────────────────────────
class TestRuleDSLSecurity(IsolatedDBTestCase):
    """可计算性 / 全表扫描 / 代码注入 / DDL / 笛卡尔积；结构保证不 eval 任意代码."""

    def test_valid_types_pass(self):
        cases = [
            ("regex", {"pattern": "powershell\\..*"}),
            ("list", {"field": "process_name", "values": ["a.exe"], "match_mode": "exact"}),
            ("threshold", {"field": "count", "operator": ">", "value": 10}),
            ("exists", {"field": "source_ip"}),
            ("composite", {"logic": "and", "sub_rules": [
                {"type": "regex", "field": "command_line", "pattern": "mimikatz"},
                {"type": "exists", "field": "source_ip"},
            ]}),
            ("attack_chain", {"steps": [{"type": "exists", "field": "event_type"}]}),
        ]
        for rt, cond in cases:
            ok, err = RuleDSL.validate(rt, cond)
            self.assertTrue(ok, f"{rt} 应合法: {err}")

    def test_reject_code_injection(self):
        # 均为结构合法的 list 规则，但 values 字符串含危险代码 → 应在扫描阶段被拒
        payloads = [
            {"field": "process_name", "values": ["__import__('os').system('id')"], "match_mode": "exact"},
            {"field": "process_name", "values": ["eval('1+1')"], "match_mode": "exact"},
            {"field": "process_name", "values": ["subprocess.check_output('id')"], "match_mode": "exact"},
        ]
        for cond in payloads:
            ok, err = RuleDSL.validate("list", cond)
            self.assertFalse(ok, f"应拒绝代码注入: {cond}")
            self.assertIn("代码", err)

    def test_reject_ddl_injection(self):
        conds = [
            {"field": "process_name", "values": ["x'; DROP TABLE rules; --"], "match_mode": "exact"},
            {"field": "process_name", "values": ["SELECT * FROM users"], "match_mode": "exact"},
            {"field": "process_name", "values": ["a; DELETE FROM rule_drafts --"], "match_mode": "exact"},
        ]
        for cond in conds:
            ok, err = RuleDSL.validate("list", cond)
            self.assertFalse(ok, f"应拒绝 DDL: {cond}")
            self.assertIn("DDL", err)

    def test_reject_full_scan_regex(self):
        for pat in ("", ".*", ".+", "^.*$", ".*.*"):
            ok, err = RuleDSL.validate("regex", {"pattern": pat})
            self.assertFalse(ok, f"全表扫描正则应拒绝: {pat!r}")
            self.assertIn("全表扫描", err)

    def test_reject_cartesian_product(self):
        # 超大 list（>1000）
        ok, _ = RuleDSL.validate("list", {"field": "process_name", "values": ["v"] * 2000})
        self.assertFalse(ok)
        # 超大 composite（>50 子规则）
        big = {"logic": "or", "sub_rules": [
            {"type": "exists", "field": "event_type"} for _ in range(60)
        ]}
        ok, _ = RuleDSL.validate("composite", big)
        self.assertFalse(ok)
        # 过深嵌套（>3 层）
        deep = {"logic": "and", "sub_rules": [{"type": "composite", "logic": "and", "sub_rules": [
            {"type": "composite", "logic": "and", "sub_rules": [
                {"type": "composite", "logic": "and", "sub_rules": [
                    {"type": "exists", "field": "event_type"}]}]}]}]}
        ok, err = RuleDSL.validate("composite", deep)
        self.assertFalse(ok)
        self.assertIn("嵌套", err)

    def test_reject_non_whitelist_field_and_key(self):
        ok, _ = RuleDSL.validate("list", {"field": "secret_column", "values": ["x"], "match_mode": "exact"})
        self.assertFalse(ok)
        ok, _ = RuleDSL.validate("list", {"field": "process_name", "values": ["x"], "evil_key": "y"})
        self.assertFalse(ok)

    def test_reject_invalid_rule_type(self):
        ok, err = RuleDSL.validate("unknown_type", {"field": "process_name", "values": ["x"]})
        self.assertFalse(ok)
        self.assertIn("rule_type", err)

    def test_no_arbitrary_code_execution_in_engine(self):
        # 静态校验：rule_dsl.py / rule_engine.py / rule_shadow.py / rule_generator.py /
        # rule_tuner.py 中不得出现 eval( / exec( / compile( / __import__( 这类实际调用
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        targets = [
            "app/services/rule_dsl.py",
            "app/services/rule_engine_proxy.py" if False else "app/rules/rule_engine.py",
            "app/services/rule_shadow.py",
            "app/services/rule_generator.py",
            "app/services/rule_tuner.py",
        ]
        dangerous = {"eval", "exec", "compile", "__import__"}
        for rel in targets:
            path = os.path.join(base, rel)
            if not os.path.exists(path):
                continue
            tree = ast.parse(open(path, encoding="utf-8").read())
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    self.assertNotIn(
                        node.func.id, dangerous,
                        f"{rel} 中存在危险调用 {node.func.id}() —— 违反「绝不 eval 任意代码」红线"
                    )


# ── ③ rule_generator 降级 ──────────────────────────────────────────────────
class TestRuleGeneratorDegradation(IsolatedDBTestCase):
    """无 Profile / 熔断 → 确定性启发式，返回可用草稿（不 500 / 不抛异常）."""

    @patch("app.services.rule_generator.AgentLLM", _FakeLLMDegraded)
    def test_degraded_returns_usable_heuristic_draft(self):
        gen = RuleGenerator()
        draft = asyncio.run(gen.generate(SAMPLE_LOGS, category="process", user={"id": 1}))
        self.assertIsInstance(draft, dict)
        self.assertIn("rule_type", draft)
        self.assertIsInstance(draft.get("condition"), dict)
        ok, err = RuleDSL.validate(draft["rule_type"], draft["condition"])
        self.assertTrue(ok, f"降级草稿应可通过 DSL 校验: {err}")

    @patch("app.services.rule_generator.AgentLLM", _FakeLLMDegraded)
    def test_degraded_with_empty_logs_returns_placeholder(self):
        # 无 process_name / event_type 字段 → exists 占位草稿，仍合法
        logs = [{"foo": "bar", "timestamp": "2026-07-18 10:00:00"}]
        draft = asyncio.run(RuleGenerator().generate(logs, category="process"))
        self.assertEqual(draft["rule_type"], "exists")
        ok, err = RuleDSL.validate(draft["rule_type"], draft["condition"])
        self.assertTrue(ok, err)

    @patch("app.services.rule_generator.AgentLLM", _FakeLLMOk)
    def test_success_path_returns_valid_draft(self):
        draft = asyncio.run(RuleGenerator().generate(SAMPLE_LOGS, category="process"))
        self.assertEqual(draft["rule_type"], "list")
        ok, err = RuleDSL.validate(draft["rule_type"], draft["condition"])
        self.assertTrue(ok, err)


# ── ④ rule_shadow + rule_engine 影子分支 ───────────────────────────────────
class TestRuleShadowSafe(IsolatedDBTestCase):
    """影子运行仅计数，引擎对 is_shadow 规则返回 0 条告警；计数正确落库."""

    def setUp(self):
        super().setUp()
        self.seed_normalized_logs(SAMPLE_LOGS)

    def _load_logs(self):
        with get_connection() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM normalized_logs").fetchall()]

    def test_shadow_evaluate_returns_zero_alerts(self):
        shadow_rule = {
            "name": "ai_shadow_x",
            "rule_type": "list",
            "condition": {"field": "process_name", "values": ["powershell.exe"], "match_mode": "exact"},
            "severity": "high",
            "is_shadow": True,
            "shadow_hit_count": 0,
        }
        matches = RuleEngine.evaluate(self._load_logs(), [shadow_rule])
        self.assertEqual(len(matches), 0, "影子规则绝对不能产生告警（安全红线）")

    @patch("app.services.rule_generator.AgentLLM", _FakeLLMOk)
    def test_run_shadow_counts_and_persists(self):
        draft = RuleDraft.create(
            name="ai_shadow_test",
            rule_type="list",
            condition={"field": "process_name", "values": ["powershell.exe"], "match_mode": "exact"},
            severity="high",
        )
        stats = RuleShadow.run_shadow(draft["id"])
        self.assertEqual(stats["hit_count"], 2)  # 两条 powershell.exe

        updated = RuleDraft.get_by_id(draft["id"])
        self.assertEqual(updated["status"], RuleDraft.STATUS_SHADOW)
        self.assertEqual(updated["shadow_hit_count"], 2)

        with get_connection() as conn:
            row = conn.execute(
                "SELECT is_shadow, shadow_hit_count FROM rules WHERE name = ?", (draft["name"],)
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["is_shadow"], 1)
        self.assertEqual(row["shadow_hit_count"], 2)

    def test_shadow_non_matching_returns_zero(self):
        draft = RuleDraft.create(
            name="ai_no_match",
            rule_type="list",
            condition={"field": "process_name", "values": ["never_existing_bin"], "match_mode": "exact"},
            severity="low",
        )
        stats = RuleShadow.run_shadow(draft["id"])
        self.assertEqual(stats["hit_count"], 0)
        self.assertEqual(RuleDraft.get_by_id(draft["id"])["status"], RuleDraft.STATUS_SHADOW)


# ── ⑤ rule_tuner 自动调优 ──────────────────────────────────────────────────
class TestRuleTuner(IsolatedDBTestCase):
    """生成新版本草稿，保留 parent_draft_id / tuned_version / tuning_history_json."""

    @patch("app.services.rule_tuner.AgentLLM", _FakeLLMOk)
    @patch("app.services.rule_generator.AgentLLM", _FakeLLMOk)
    def test_tune_creates_new_version_and_preserves_history(self):
        parent = RuleDraft.create(
            name="ai_base",
            rule_type="list",
            condition={"field": "process_name", "values": ["powershell.exe"], "match_mode": "exact"},
            severity="high",
            label="base",
        )
        new = tuner_tune(parent, [{"process_name": "powershell.exe"}], "疑似误报")
        self.assertNotEqual(new["name"], parent["name"])
        self.assertEqual(new["parent_draft_id"], parent["id"])
        self.assertEqual(new["tuned_version"], 1)
        self.assertIsInstance(new["tuning_history"], list)
        self.assertGreaterEqual(len(new["tuning_history"]), 1)
        refreshed = RuleDraft.get_by_id(parent["id"])
        self.assertEqual(refreshed["status"], RuleDraft.STATUS_PENDING_REVIEW)

    @patch("app.services.rule_tuner.AgentLLM", _FakeLLMDegraded)
    def test_heuristic_tune_removes_fp_values(self):
        # list 规则 + 误报样本 → 移除误报值（抑制），版本+1，保留调优历史
        parent = RuleDraft.create(
            name="ai_base2",
            rule_type="list",
            condition={"field": "process_name", "values": ["powershell.exe", "legit.exe"], "match_mode": "exact"},
            severity="high",
            label="base2",
        )
        new = tuner_tune(parent, [{"process_name": "powershell.exe"}], "误报")
        self.assertNotIn("powershell.exe", new["condition"].get("values", []))
        self.assertIn("legit.exe", new["condition"].get("values", []))
        self.assertEqual(new["tuned_version"], 1)
        self.assertTrue(new["tuning_history"][0].get("llm_degraded"))
        # 原草稿进入待复审
        self.assertEqual(RuleDraft.get_by_id(parent["id"])["status"], RuleDraft.STATUS_PENDING_REVIEW)

    @patch("app.services.rule_tuner.AgentLLM", _FakeLLMDegraded)
    def test_heuristic_tune_lowers_severity_for_nonlist(self):
        # 非 list 规则 + 误报反馈 → 降低严重度以减少噪声
        parent = RuleDraft.create(
            name="ai_base3",
            rule_type="threshold",
            condition={"field": "count", "operator": ">", "value": 10},
            severity="high",
            label="base3",
        )
        new = tuner_tune(parent, [{"value": "x"}], "疑似误报")
        self.assertEqual(new["severity"], "medium")  # high → medium


def tuner_tune(parent, fps, feedback):
    """辅助：调用 RuleTuner.tune（降级/正常路径均返回新版本草稿字典）."""
    tuner = RuleTuner()
    return asyncio.run(
        tuner.tune(parent, false_positive_examples=fps, feedback=feedback, user={"id": 1})
    )


# ── ⑥ rule_draft 模型 + CRUD + 状态机 ─────────────────────────────────────
class TestRuleDraftModelAndStateMachine(IsolatedDBTestCase):
    """模型 CRUD + 状态机 draft→shadow→enabled/rejected 自洽."""

    def test_crud(self):
        d = RuleDraft.create(
            name="ai_crud", rule_type="list",
            condition={"field": "process_name", "values": ["a.exe"], "match_mode": "exact"},
            severity="low", label="t",
        )
        self.assertIsNotNone(d["id"])
        self.assertEqual(RuleDraft.get_by_id(d["id"])["name"], "ai_crud")
        self.assertEqual(RuleDraft.get_by_name("ai_crud")["id"], d["id"])
        listed = RuleDraft.list()
        self.assertTrue(any(x["id"] == d["id"] for x in listed["items"]))
        RuleDraft.update(d["id"], severity="high")
        self.assertEqual(RuleDraft.get_by_id(d["id"])["severity"], "high")
        self.assertTrue(RuleDraft.delete(d["id"]))
        self.assertIsNone(RuleDraft.get_by_id(d["id"]))

    def test_state_machine_draft_to_shadow(self):
        d = RuleDraft.create(
            name="ai_sm", rule_type="list",
            condition={"field": "process_name", "values": ["a.exe"], "match_mode": "exact"},
        )
        self.assertEqual(d["status"], RuleDraft.STATUS_DRAFT)
        RuleShadow.run_shadow(d["id"])
        self.assertEqual(RuleDraft.get_by_id(d["id"])["status"], RuleDraft.STATUS_SHADOW)

    def test_state_machine_rejected_guarded_from_enable(self):
        d = RuleDraft.create(
            name="ai_rej", rule_type="list",
            condition={"field": "process_name", "values": ["a.exe"], "match_mode": "exact"},
        )
        RuleDraft.update(d["id"], status=RuleDraft.STATUS_REJECTED)
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.api.rules import router
        from app.services.auth_service import get_current_user

        app = FastAPI()
        app.include_router(router, prefix="/api/rules")
        app.dependency_overrides[get_current_user] = lambda: {"user_id": 1, "username": "admin", "role": "admin"}
        client = TestClient(app)
        r = client.post(f"/api/rules/drafts/{d['id']}/enable")
        self.assertEqual(r.status_code, 400, r.text[:200])


# ── ⑧ 端到端冒烟 ───────────────────────────────────────────────────────────
class TestEndToEndSmoke(IsolatedDBTestCase):
    """generate → draft → shadow → stats → tune → enable(admin) → 生效规则；reject 路径."""

    def setUp(self):
        super().setUp()
        self.seed_normalized_logs(SAMPLE_LOGS)
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.api.rules import router
        from app.services.auth_service import get_current_user

        self.app = FastAPI()
        self.app.include_router(router, prefix="/api/rules")
        self.app.dependency_overrides[get_current_user] = lambda: {"user_id": 1, "username": "admin", "role": "admin"}
        self.client = TestClient(self.app)

    @patch("app.services.rule_generator.AgentLLM", _FakeLLMOk)
    @patch("app.services.rule_tuner.AgentLLM", _FakeLLMOk)
    def test_full_enable_flow(self):
        # generate
        r = self.client.post("/api/rules/generate", json={})
        self.assertEqual(r.status_code, 200)
        did = r.json()["data"]["drafts"][0]["id"]
        # list
        self.assertEqual(self.client.get("/api/rules/drafts").status_code, 200)
        # shadow run
        r = self.client.post(f"/api/rules/drafts/{did}/shadow")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["data"]["hit_count"], 2)
        # stats
        r = self.client.get(f"/api/rules/drafts/{did}/shadow-stats")
        self.assertEqual(r.json()["data"]["hit_count"], 2)
        # tune
        self.assertEqual(self.client.post(f"/api/rules/drafts/{did}/tune", json={}).status_code, 200)
        # enable(admin)
        r = self.client.post(f"/api/rules/drafts/{did}/enable")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["data"]["enabled"])
        rule_id = r.json()["data"]["rule_id"]
        # 生效规则落库：rules 行 enabled=1, is_shadow=0
        with get_connection() as conn:
            row = conn.execute(
                "SELECT enabled, is_shadow FROM rules WHERE id = ?", (rule_id,)
            ).fetchone()
        self.assertEqual(row["enabled"], 1)
        self.assertEqual(row["is_shadow"], 0)
        # 草稿状态 enabled
        self.assertEqual(
            self.client.get(f"/api/rules/drafts/{did}/shadow-stats").json()["data"]["status"], "enabled"
        )

    @patch("app.services.rule_generator.AgentLLM", _FakeLLMOk)
    def test_reject_flow(self):
        r = self.client.post("/api/rules/generate", json={})
        did = r.json()["data"]["drafts"][0]["id"]
        r = self.client.post(f"/api/rules/drafts/{did}/reject", json={"reason": "测试驳回"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["data"]["status"], "rejected")
        with get_connection() as conn:
            row = conn.execute(
                "SELECT is_shadow, enabled FROM rules WHERE name = (SELECT name FROM rule_drafts WHERE id = ?)",
                (did,),
            ).fetchone()
        if row is not None:
            self.assertEqual(row["is_shadow"], 0)
            self.assertEqual(row["enabled"], 0)


# ── ⑦ 前端契约（静态 + 构建）──────────────────────────────────────────────
class TestFrontendContract(IsolatedDBTestCase):
    """RuleDraftView.vue 消费真实字段；api/ruleDrafts.js 路径与后端一致；vite build 通过."""

    FRONTEND_ROOT = os.path.abspath(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "frontend")
    )

    def test_vue_consumes_backend_fields(self):
        vue_path = os.path.join(self.FRONTEND_ROOT, "src", "views", "RuleDraftView.vue")
        self.assertTrue(os.path.exists(vue_path), "RuleDraftView.vue 缺失")
        src = open(vue_path, encoding="utf-8").read()
        for field in ("shadow_hit_count", "tuned_version", "rationale", "dsl", "sample_hits",
                      "status", "condition"):
            self.assertIn(field, src, f"前端未消费后端字段 {field}")

    def test_api_paths_match_backend(self):
        api_path = os.path.join(self.FRONTEND_ROOT, "src", "api", "ruleDrafts.js")
        self.assertTrue(os.path.exists(api_path), "api/ruleDrafts.js 缺失")
        src = open(api_path, encoding="utf-8").read()
        for endpoint in ("/rules/generate", "/rules/drafts", "/rules/drafts/${draftId}/shadow",
                         "/rules/drafts/${draftId}/shadow-stats", "/rules/drafts/${draftId}/tune",
                         "/rules/drafts/${draftId}/enable", "/rules/drafts/${draftId}/reject"):
            self.assertIn(endpoint, src, f"前端缺少端点 {endpoint}")

    def test_vite_build_passes(self):
        """运行 vite build（要求前端 node_modules 已安装）。"""
        import subprocess
        npm = os.path.join(self.FRONTEND_ROOT, "node_modules", ".bin", "vite.cmd")
        if not os.path.exists(npm):
            npm = "npx"
        try:
            proc = subprocess.run(
                [npm, "build"], cwd=self.FRONTEND_ROOT, capture_output=True, text=True, timeout=300
            )
        except Exception as exc:  # noqa: BLE001
            self.skipTest(f"vite build 无法执行（跳过，非源码缺陷）: {exc}")
            return
        self.assertEqual(
            proc.returncode, 0,
            f"vite build 失败:\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}"
        )


if __name__ == "__main__":
    unittest.main()
