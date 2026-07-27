"""可配置默认闭环流程（config-default-pipeline）QA 测试套件.

覆盖（架构 §3 / PRD P0）：
- A. 后端逻辑：
  1) resolve_default_pipeline 三级解析（scene → global → hardcoded）；
  2) 事件属性映射（security_events → category/priority）；
  3) 默认规则 CRUD + 全局默认唯一性 + 删全局回退；
  4) validate_default_pipeline（必须含 responder；reporter 缺失仅告警）；
  5) create_agent_run 分支（preset_id / resolve 命中 / 硬编码兜底）；
  6) ensure_reporter（尾部补 reporter）；
  7) resume 模式感知（custom 刷新 reporter 不重复 / hardcoded 走 _finish_with_reporter）。

复用 _qa_batch1_common.IsolatedDBTestCase 隔离 SQLite（绝不触碰 ir.db）。
API 测试挂最小 app（仅 agents.router，prefix=/api），用 dependency_overrides 注入用户。
"""

import asyncio
import json
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

import sys

_THIS = Path(__file__).resolve().parent
_BACKEND = _THIS.parent
for _p in (str(_BACKEND), str(_THIS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.agents import router as agents_router
from app.services.auth_service import get_current_user
from app.database import get_connection
from app.models.agent_definition import PipelinePresetModel
from app.models.agent_run import AgentRun, AgentRunStep
from app.services.agents.default_pipeline_service import (
    DefaultPipelineService,
    DefaultPipelineError,
    GlobalDefaultConflict,
)

from _qa_batch1_common import IsolatedDBTestCase

# 一组「合法默认 pipeline」：含 responder + reporter，且依赖闭环被满足
VALID_DEFAULT_AGENTS = [
    "triage", "file_analysis", "process_analysis", "network_analysis",
    "root_cause", "responder", "reporter",
]


def _make_preset(conn, name="标准应急响应链", agents=None):
    """在隔离库创建一条 pipeline_presets，返回 preset dict。"""
    return PipelinePresetModel.create({
        "name": name,
        "description": "qa preset",
        "agents": agents or VALID_DEFAULT_AGENTS,
    })


def _seed_host_event(conn, event_id="SE-1", event_type="ransomware", severity="critical"):
    """写 host + security_events（仅数据库既有列）。"""
    # 先建 case 以满足 hosts.case_id 外键约束
    conn.execute("INSERT INTO cases (name) VALUES ('qa_case')")
    case_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO hosts (case_id, hostname, ip_address, os_type) "
        "VALUES (?, 'QAHOST', '10.0.0.9', 'Windows')", (case_id,))
    host_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO security_events "
        "(id, timestamp, host_id, event_type, event_key, severity, status) "
        "VALUES (?, '2026-07-18 10:00:00', ?, ?, 'ek1', ?, 'pending')",
        (event_id, host_id, event_type, severity))
    return host_id


# ──────────────────────────────────────────────────────────────
# 最小 API app（仅编排路由）
# ──────────────────────────────────────────────────────────────
_api_app = FastAPI()
_api_app.include_router(agents_router, prefix="/api")


class _Base(IsolatedDBTestCase):
    def setUp(self):
        super().setUp()
        self.svc = DefaultPipelineService()
        self.client = TestClient(_api_app)
        _api_app.dependency_overrides.clear()
        # 隔离库无 agent_definitions 种子数据，mock AgentRegistry.validate_pipeline 返回 []
        # 使 create_rule → validate_default_pipeline 不因 "Agent not found" 阻断
        self._reg_patcher = patch(
            'app.services.agents.agent_registry.AgentRegistry.validate_pipeline',
            return_value=[])
        self._reg_patcher.start()

    def tearDown(self):
        self._reg_patcher.stop()
        _api_app.dependency_overrides.clear()
        super().tearDown()

    def _auth(self, role="admin"):
        user = {
            "id": 1 if role == "admin" else 2,
            "username": "admin" if role == "admin" else "analyst",
            "role": role,
        }
        _api_app.dependency_overrides[get_current_user] = lambda: user
        return user

    def conn(self):
        """返回数据库连接上下文管理器（兼容 _make_preset 签名，实际未使用 conn）。"""
        return get_connection()


# ════════════════════════════════════════════════════════════════
# 1) resolve_default_pipeline 三级解析
# ════════════════════════════════════════════════════════════════
class TestResolveThreeLevel(_Base):
    def test_no_rules_falls_back_to_hardcoded(self):
        r = self.svc.resolve_default_pipeline({"event_id": "SE-1"})
        self.assertEqual(r.match_type, "hardcoded")
        self.assertIsNone(r.preset_id)
        self.assertIsNone(r.agent_names)
        self.assertIsNone(r.rule_id)

    def test_global_default_only(self):
        preset = _make_preset(self.conn(), name="全局标准链")
        self.svc.create_rule(
            {"preset_id": preset["id"], "is_global": True}, user={"username": "admin"})
        r = self.svc.resolve_default_pipeline({"event_id": "SE-1"})
        self.assertEqual(r.match_type, "global")
        self.assertTrue(r.is_global)
        self.assertEqual(r.preset_id, preset["id"])
        self.assertEqual(r.agent_names, VALID_DEFAULT_AGENTS)
        self.assertIsNotNone(r.rule_id)

    def test_scene_rule_matches_by_explicit_category_priority(self):
        preset = _make_preset(self.conn(), name="勒索软件链")
        self.svc.create_rule(
            {"preset_id": preset["id"],
             "scene_condition": {"category": "ransomware", "priority": "P0"}},
            user={"username": "admin"})
        r = self.svc.resolve_default_pipeline(
            {"event_id": "SE-1", "category": "ransomware", "priority": "P0"})
        self.assertEqual(r.match_type, "scene")
        self.assertEqual(r.preset_id, preset["id"])
        self.assertEqual(r.agent_names, VALID_DEFAULT_AGENTS)

    def test_scene_null_dimension_is_no_constraint(self):
        """scene_condition 某维度为 null = 不约束（AND 语义）。"""
        preset = _make_preset(self.conn(), name="勒索软件链")
        # 仅约束 category，priority=None
        self.svc.create_rule(
            {"preset_id": preset["id"],
             "scene_condition": {"category": "ransomware", "priority": None}},
            user={"username": "admin"})
        r = self.svc.resolve_default_pipeline(
            {"event_id": "SE-1", "category": "ransomware", "priority": "P0"})
        self.assertEqual(r.match_type, "scene")
        self.assertEqual(r.preset_id, preset["id"])

    def test_scene_category_mismatch_falls_through(self):
        preset = _make_preset(self.conn(), name="勒索软件链")
        self.svc.create_rule(
            {"preset_id": preset["id"],
             "scene_condition": {"category": "ransomware", "priority": "P0"}},
            user={"username": "admin"})
        # category 不匹配 → 命中不了场景规则
        r = self.svc.resolve_default_pipeline(
            {"event_id": "SE-1", "category": "portscan", "priority": "P0"})
        self.assertEqual(r.match_type, "hardcoded")

    def test_multiple_scene_rules_more_specific_wins(self):
        """多条场景规则命中时，更具体（维度更全）优先；确定性可复现。"""
        p_a = _make_preset(self.conn(), name="通用端口扫描链")
        p_b = _make_preset(self.conn(), name="勒索+P0 重链")
        # 规则1：仅 category=portscan
        self.svc.create_rule(
            {"preset_id": p_a["id"],
             "scene_condition": {"category": "portscan", "priority": None},
             "priority_order": 0}, user={"username": "admin"})
        # 规则2：category=portscan AND priority=P0（更具体）
        self.svc.create_rule(
            {"preset_id": p_b["id"],
             "scene_condition": {"category": "portscan", "priority": "P0"},
             "priority_order": 1}, user={"username": "admin"})
        r = self.svc.resolve_default_pipeline(
            {"event_id": "SE-1", "category": "portscan", "priority": "P0"})
        self.assertEqual(r.match_type, "scene")
        self.assertEqual(r.preset_id, p_b["id"], "更具体的规则应优先命中")

    def test_scene_falls_to_global_when_no_match(self):
        p_scene = _make_preset(self.conn(), name="勒索软件链")
        p_global = _make_preset(self.conn(), name="全局标准链")
        self.svc.create_rule(
            {"preset_id": p_scene["id"],
             "scene_condition": {"category": "ransomware", "priority": "P0"}},
            user={"username": "admin"})
        self.svc.create_rule(
            {"preset_id": p_global["id"], "is_global": True},
            user={"username": "admin"})
        # 不匹配场景 → 走全局
        r = self.svc.resolve_default_pipeline(
            {"event_id": "SE-1", "category": "other", "priority": "P3"})
        self.assertEqual(r.match_type, "global")
        self.assertEqual(r.preset_id, p_global["id"])


# ════════════════════════════════════════════════════════════════
# 2) 事件属性映射（security_events → category/priority）
# ════════════════════════════════════════════════════════════════
class TestEventAttributeMapping(_Base):
    def test_map_event_type_severity_to_category_priority(self):
        """架构 §7.4：category ← event_type，priority ← severity 映射。
        仅传 event_id，应从 security_events 映射出 category/priority。"""
        with get_connection() as conn:
            host_id = _seed_host_event(
                conn, event_id="SE-77", event_type="ransomware", severity="critical")
        attrs = self.svc._load_event_attributes("SE-77")
        self.assertEqual(attrs.get("category"), "ransomware")
        self.assertEqual(attrs.get("priority"), "P0")

    def test_severity_low_maps_to_p3(self):
        with get_connection() as conn:
            _seed_host_event(conn, event_id="SE-78", event_type="portscan", severity="low")
        attrs = self.svc._load_event_attributes("SE-78")
        self.assertEqual(attrs.get("category"), "portscan")
        self.assertEqual(attrs.get("priority"), "P3")

    def test_resolve_uses_mapped_attributes_from_db(self):
        """端到端：仅 event_id（无显式 category/priority）→ 命中 scene 规则。"""
        with get_connection() as conn:
            _seed_host_event(
                conn, event_id="SE-77", event_type="ransomware", severity="critical")
        preset = _make_preset(self.conn(), name="勒索软件链")
        self.svc.create_rule(
            {"preset_id": preset["id"],
             "scene_condition": {"category": "ransomware", "priority": "P0"}},
            user={"username": "admin"})
        # 仅传 event_id，依赖 DB 映射
        r = self.svc.resolve_default_pipeline({"event_id": "SE-77"})
        self.assertEqual(r.match_type, "scene")
        self.assertEqual(r.preset_id, preset["id"])


# ════════════════════════════════════════════════════════════════
# 3) 默认规则 CRUD
# ════════════════════════════════════════════════════════════════
class TestRuleCRUD(_Base):
    def test_create_and_list(self):
        preset = _make_preset(self.conn(), name="勒索软件链")
        rule = self.svc.create_rule(
            {"preset_id": preset["id"],
             "scene_condition": {"category": "ransomware", "priority": "P0"}},
            user={"username": "admin"})
        self.assertIsNotNone(rule["id"])
        rules = self.svc.list_rules()
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]["preset_name"], "勒索软件链")
        self.assertEqual(rules[0]["agent_count"], len(VALID_DEFAULT_AGENTS))

    def test_create_nonexistent_preset_raises(self):
        with self.assertRaises(DefaultPipelineError):
            self.svc.create_rule(
                {"preset_id": 99999,
                 "scene_condition": {"category": "x"}},
                user={"username": "admin"})

    def test_second_global_conflict_409(self):
        p1 = _make_preset(self.conn(), name="G1")
        p2 = _make_preset(self.conn(), name="G2")
        self.svc.create_rule(
            {"preset_id": p1["id"], "is_global": True}, user={"username": "admin"})
        with self.assertRaises(GlobalDefaultConflict) as ctx:
            self.svc.create_rule(
                {"preset_id": p2["id"], "is_global": True}, user={"username": "admin"})
        self.assertEqual(ctx.exception.status_code, 409)

    def test_update_rule(self):
        preset = _make_preset(self.conn(), name="链")
        rule = self.svc.create_rule(
            {"preset_id": preset["id"],
             "scene_condition": {"category": "ransomware", "priority": None}},
            user={"username": "admin"})
        updated = self.svc.update_rule(
            rule["id"], {"scene_condition": {"category": "portscan", "priority": "P1"}})
        self.assertEqual(updated["scene_condition"], {"category": "portscan", "priority": "P1"})

    def test_update_to_global_conflicts(self):
        p1 = _make_preset(self.conn(), name="G1")
        p2 = _make_preset(self.conn(), name="G2")
        self.svc.create_rule({"preset_id": p1["id"], "is_global": True},
                             user={"username": "admin"})
        scene_rule = self.svc.create_rule(
            {"preset_id": p2["id"], "scene_condition": {"category": "x"}},
            user={"username": "admin"})
        with self.assertRaises(GlobalDefaultConflict):
            self.svc.update_rule(scene_rule["id"], {"is_global": True})

    def test_delete_global_falls_back_to_hardcoded(self):
        preset = _make_preset(self.conn(), name="G")
        rule = self.svc.create_rule(
            {"preset_id": preset["id"], "is_global": True}, user={"username": "admin"})
        res = self.svc.delete_rule(rule["id"])
        self.assertTrue(res["deleted"])
        self.assertTrue(res["fell_back_to_hardcoded"])
        # 删后无规则 → resolve 走 hardcoded
        r = self.svc.resolve_default_pipeline({"event_id": "SE-1"})
        self.assertEqual(r.match_type, "hardcoded")

    def test_delete_nonexistent_raises(self):
        with self.assertRaises(DefaultPipelineError):
            self.svc.delete_rule(99999)

    def test_preset_referenced_by_multiple_rules(self):
        """Q7：同一 pipeline 可被多条场景规则引用。"""
        preset = _make_preset(self.conn(), name="链")
        r1 = self.svc.create_rule(
            {"preset_id": preset["id"],
             "scene_condition": {"category": "a", "priority": None}},
            user={"username": "admin"})
        r2 = self.svc.create_rule(
            {"preset_id": preset["id"],
             "scene_condition": {"category": "b", "priority": None}},
            user={"username": "admin"})
        self.assertNotEqual(r1["id"], r2["id"])
        self.assertEqual(len(self.svc.list_rules()), 2)


# ════════════════════════════════════════════════════════════════
# 4) validate_default_pipeline
# ════════════════════════════════════════════════════════════════
class TestValidateDefaultPipeline(_Base):
    def test_missing_responder_is_error(self):
        errs = self.svc.validate_default_pipeline(["triage", "reporter"])
        self.assertTrue(any("responder" in e for e in errs))

    def test_missing_reporter_is_only_warning(self):
        """reporter 缺失仅告警（引擎 ensure_reporter 保底），不阻断。"""
        errs = self.svc.validate_default_pipeline(["triage", "root_cause", "responder"])
        self.assertFalse(any("reporter" in e for e in errs))
        self.assertFalse(any("responder" in e for e in errs))

    def test_empty_pipeline_is_error(self):
        errs = self.svc.validate_default_pipeline([])
        self.assertTrue(errs)

    def test_valid_pipeline_passes(self):
        errs = self.svc.validate_default_pipeline(VALID_DEFAULT_AGENTS)
        self.assertEqual(errs, [])


# ════════════════════════════════════════════════════════════════
# 5) API 鉴权 + create_agent_run 分支
# ════════════════════════════════════════════════════════════════
class TestAPIAndRunBranches(_Base):
    def test_resolve_preview_requires_auth(self):
        _api_app.dependency_overrides.clear()
        resp = self.client.get("/api/agents/default-pipelines/resolve?event_id=SE-1")
        self.assertEqual(resp.status_code, 401)

    def test_resolve_preview_ok_for_any_role(self):
        self._auth("analyst")
        resp = self.client.get("/api/agents/default-pipelines/resolve?event_id=SE-1")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data"]["match_type"], "hardcoded")

    def test_create_requires_admin_403(self):
        self._auth("analyst")
        preset = _make_preset(self.conn())
        resp = self.client.post(
            "/api/agents/default-pipelines",
            json={"preset_id": preset["id"], "is_global": True})
        self.assertEqual(resp.status_code, 403)

    def test_update_delete_requires_admin_403(self):
        self._auth("admin")
        preset = _make_preset(self.conn())
        cr = self.client.post(
            "/api/agents/default-pipelines",
            json={"preset_id": preset["id"], "is_global": True})
        rule_id = cr.json()["data"]["id"]
        # 切换为 analyst 再试
        self._auth("analyst")
        up = self.client.put(
            f"/api/agents/default-pipelines/{rule_id}",
            json={"scene_condition": {"category": "x"}})
        self.assertEqual(up.status_code, 403)
        de = self.client.delete(f"/api/agents/default-pipelines/{rule_id}")
        self.assertEqual(de.status_code, 403)

    def test_create_rule_via_api_admin(self):
        self._auth("admin")
        preset = _make_preset(self.conn(), name="链")
        resp = self.client.post(
            "/api/agents/default-pipelines",
            json={"preset_id": preset["id"],
                  "scene_condition": {"category": "ransomware"}})
        self.assertEqual(resp.status_code, 200)
        self.assertIsNotNone(resp.json()["data"]["id"])

    def test_create_run_with_preset_id_uses_custom(self):
        self._auth("admin")
        preset = _make_preset(self.conn(), name="手动链")
        resp = self.client.post(
            "/api/agents/run", json={"event_id": "SE-1", "preset_id": preset["id"]})
        self.assertEqual(resp.status_code, 200)
        run_id = resp.json()["data"]["run_id"]
        run = AgentRun.get_by_run_id(run_id)
        ctx = json.loads(run["ctx_json"])
        self.assertEqual(ctx["mode"], "custom")
        self.assertEqual(ctx["agent_names"], VALID_DEFAULT_AGENTS)

    def test_create_run_no_rules_falls_back_hardcoded(self):
        self._auth("admin")
        resp = self.client.post("/api/agents/run", json={"event_id": "SE-1"})
        self.assertEqual(resp.status_code, 200)
        run_id = resp.json()["data"]["run_id"]
        run = AgentRun.get_by_run_id(run_id)
        ctx = json.loads(run["ctx_json"])
        self.assertNotIn("mode", ctx)  # 硬编码路径不写 mode

    def test_create_run_resolve_global_uses_custom(self):
        self._auth("admin")
        preset = _make_preset(self.conn(), name="全局链")
        self.svc.create_rule(
            {"preset_id": preset["id"], "is_global": True}, user={"username": "admin"})
        resp = self.client.post("/api/agents/run", json={"event_id": "SE-1"})
        self.assertEqual(resp.status_code, 200)
        run_id = resp.json()["data"]["run_id"]
        run = AgentRun.get_by_run_id(run_id)
        ctx = json.loads(run["ctx_json"])
        self.assertEqual(ctx["mode"], "custom")
        self.assertEqual(ctx["resolved_match_type"], "global")

    def test_resolve_preview_explicit_override(self):
        self._auth("admin")
        preset = _make_preset(self.conn(), name="勒索软件链")
        self.svc.create_rule(
            {"preset_id": preset["id"],
             "scene_condition": {"category": "ransomware", "priority": "P0"}},
            user={"username": "admin"})
        resp = self.client.get(
            "/api/agents/default-pipelines/resolve"
            "?category=ransomware&priority=P0")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data"]["match_type"], "scene")
        self.assertEqual(resp.json()["data"]["preset_id"], preset["id"])


# ════════════════════════════════════════════════════════════════
# 6) ensure_reporter（尾部补 reporter）
# ════════════════════════════════════════════════════════════════
class TestEnsureReporter(_Base):
    def _make_fake_agent_def(self, name):
        """构造一个 fake AgentDefinition（hitl=False，避免触发 HITL 分支）。"""
        ad = MagicMock()
        ad.name = name
        ad.hitl = False
        ad.enabled = True
        ad.depends_on = []
        return ad

    def test_engine_appends_reporter_when_missing(self):
        from app.services.agents.pipeline_engine import PipelineEngine
        from app.services.agents.agent_registry import AgentRegistry

        async def fake_exec(agent_def, run):
            return {"stage": agent_def.name, "output": "ok",
                    "confidence": 0.5, "evidence": [], "hitl_triggered": False}

        engine = PipelineEngine()
        fake_graph = {"triage": [], "reporter": []}
        with patch.object(AgentRegistry, "get_dependency_graph", return_value=fake_graph), \
                patch.object(AgentRegistry, "get", side_effect=self._make_fake_agent_def), \
                patch.object(PipelineEngine, "_execute_agent", side_effect=fake_exec):
            result = asyncio.run(engine.run(
                run_id="run_reporter_1",
                agent_names=["triage"],
                event_id="SE-1",
                ctx={"event_id": "SE-1"},
                user={"id": 1},
                use_cache=False,
                ensure_reporter=True,
            ))
        self.assertEqual(result["status"], "completed")
        # reporter 被追加
        steps = AgentRunStep.list_by_run("run_reporter_1")
        agent_steps = [s["agent"] for s in steps]
        self.assertIn("reporter", agent_steps)
        # 末尾为 reporter
        self.assertEqual(agent_steps[-1], "reporter")

    def test_engine_does_not_duplicate_reporter(self):
        from app.services.agents.pipeline_engine import PipelineEngine
        from app.services.agents.agent_registry import AgentRegistry

        async def fake_exec(agent_def, run):
            return {"stage": agent_def.name, "output": "ok",
                    "confidence": 0.5, "evidence": [], "hitl_triggered": False}

        engine = PipelineEngine()
        fake_graph = {"triage": [], "reporter": []}
        with patch.object(AgentRegistry, "get_dependency_graph", return_value=fake_graph), \
                patch.object(AgentRegistry, "get", side_effect=self._make_fake_agent_def), \
                patch.object(PipelineEngine, "_execute_agent", side_effect=fake_exec):
            asyncio.run(engine.run(
                run_id="run_reporter_2",
                agent_names=["triage", "reporter"],
                event_id="SE-1",
                ctx={"event_id": "SE-1"},
                user={"id": 1},
                use_cache=False,
                ensure_reporter=True,
            ))
        steps = [s["agent"] for s in AgentRunStep.list_by_run("run_reporter_2")]
        self.assertEqual(steps.count("reporter"), 1)


# ════════════════════════════════════════════════════════════════
# 7) resume 模式感知（custom 刷新 reporter / hardcoded 走 _finish）
# ════════════════════════════════════════════════════════════════
class TestResumeModeAwareness(_Base):
    def _make_custom_run_with_reporter_step(self, run_id="run_resume_1"):
        AgentRun.create(
            run_id=run_id, event_id="SE-1", title="qa",
            stage="response", status="waiting_hitl", priority="P0", user_id=1,
            ctx_json=json.dumps({"mode": "custom", "agent_names": VALID_DEFAULT_AGENTS,
                                  "event_id": "SE-1"}))
        AgentRunStep.add(run_id=run_id, stage="report", agent="reporter",
                         status="success", output_json={"old": True})
        return run_id

    def test_resume_custom_refreshes_reporter_not_duplicate(self):
        from app.services.agents.orchestrator import Orchestrator

        run_id = self._make_custom_run_with_reporter_step()
        orch = Orchestrator()
        hitl = {"status": "approved", "action": "block_ip", "reason": None}
        asyncio.run(orch._resume_custom(
            run_id, ctx={"mode": "custom", "event_id": "SE-1"},
            user={"id": 1, "username": "admin", "role": "admin"},
            hitl_decision={"status": "approved"}, executed={"a": 1}))
        steps = AgentRunStep.list_by_run(run_id)
        reporter_steps = [s for s in steps if s["agent"] == "reporter"]
        self.assertEqual(len(reporter_steps), 1, "不应出现重复 reporter 步骤")
        self.assertEqual(AgentRun.get_by_run_id(run_id)["status"], "completed")
        self.assertEqual(reporter_steps[0]["status"], "success")

    def test_resume_dispatches_by_mode(self):
        from app.services.agents.orchestrator import Orchestrator

        # custom 模式 → 调用 _resume_custom，不调用 _finish_with_reporter
        AgentRun.create(
            run_id="run_disp_c", event_id="SE-1", title="qa",
            stage="response", status="waiting_hitl", priority="P0", user_id=1,
            ctx_json=json.dumps({"mode": "custom", "agent_names": VALID_DEFAULT_AGENTS,
                                  "event_id": "SE-1"}))
        orch = Orchestrator()
        approval = {"status": "approved", "action": "block_ip", "reason": None}
        with patch("app.services.agents.responder_agent.ResponderAgent.execute_action",
                   new=AsyncMock(return_value=({}, None))), \
                patch.object(Orchestrator, "_resume_custom",
                             new=AsyncMock(return_value={"status": "completed"})) as m_custom, \
                patch.object(Orchestrator, "_finish_with_reporter",
                             new=AsyncMock(return_value={"status": "completed"})) as m_finish:
            asyncio.run(orch.resume(
                "run_disp_c", approval, decided_by=1,
                user={"id": 1, "username": "admin", "role": "admin"}))
        m_custom.assert_called_once()
        m_finish.assert_not_called()

    def test_resume_hardcoded_calls_finish(self):
        from app.services.agents.orchestrator import Orchestrator

        AgentRun.create(
            run_id="run_disp_h", event_id="SE-1", title="qa",
            stage="response", status="waiting_hitl", priority="P0", user_id=1,
            ctx_json=json.dumps({"mode": "hardcoded", "event_id": "SE-1"}))
        orch = Orchestrator()
        approval = {"status": "approved", "action": "block_ip", "reason": None}
        with patch("app.services.agents.responder_agent.ResponderAgent.execute_action",
                   new=AsyncMock(return_value=({}, None))), \
                patch.object(Orchestrator, "_resume_custom",
                             new=AsyncMock(return_value={"status": "completed"})) as m_custom, \
                patch.object(Orchestrator, "_finish_with_reporter",
                             new=AsyncMock(return_value={"status": "completed"})) as m_finish:
            asyncio.run(orch.resume(
                "run_disp_h", approval, decided_by=1,
                user={"id": 1, "username": "admin", "role": "admin"}))
        m_finish.assert_called_once()
        m_custom.assert_not_called()


if __name__ == "__main__":
    import unittest
    unittest.main(verbosity=2)
