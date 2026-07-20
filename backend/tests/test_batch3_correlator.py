"""第③批 T-D1 · IncidentCorrelator 归并 + AI 高级关联 API 测试。

- 单元：``keyword`` 复用分组逻辑；``semantic`` 在 AgentLLM 降级时回退
  确定性字段聚类（host/event_type/ip）并落 incident_clusters；AgentLLM 返回
  合法 JSON 时走语义聚类；仅对 ``ai_verdict.label='suspicious'`` 归并。
- API：``POST /api/ai/correlate-incidents`` 无 token→401，带 token 且
  mode 生效；``GET /api/ai/incidents/clusters`` 无 token→401，带 token
  返回分页 + severity 过滤。

LLM 不可用路径全部覆盖（mock AgentLLM.call 抛异常 / 返回空 / degraded）。
隔离 SQLite（_qa_batch1_common），绝不触碰 ir.db。
"""

import asyncio
import json
from pathlib import Path
from unittest.mock import patch, AsyncMock

import sys
_THIS = Path(__file__).resolve().parent
_BACKEND = _THIS.parent
for _p in (str(_BACKEND), str(_THIS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.ai_advanced import router as ai_router
from app.services.auth_service import get_current_user
from app.services.incident_correlator import IncidentCorrelator
from app.models.incident_cluster import IncidentCluster
from app.database import get_connection

from _qa_batch1_common import IsolatedDBTestCase

# 隔离最小 app：仅挂 ai_advanced（prefix=/api，与主 app 一致）
_api_app = FastAPI()
_api_app.include_router(ai_router, prefix="/api")

# 语义聚类的时间窗拉到极大，避免 datetime('now','-N minutes') 把种子事件排除
BIG_WINDOW = 60 * 24 * 365 * 5


def _seed_case_host():
    with get_connection() as conn:
        conn.execute("INSERT INTO cases (name) VALUES ('qa_case')")
        case_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO hosts (case_id, hostname, ip_address, os_type) "
            "VALUES (?, 'QAHOST', '10.0.0.7', 'Windows')", (case_id,))
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def _seed_suspicious_event(eid, host_id, event_type, severity="high",
                            ip="", verdict=None, ts="2026-07-18 10:00:00"):
    verdict = verdict or {"label": "suspicious", "attack_type": "lateral",
                           "reason": "beacon", "confidence": 0.8}
    evidence = json.dumps({"source_ip": ip}) if ip else "{}"
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO security_events "
            "(id, timestamp, host_id, event_type, severity, event_key, "
            "evidence, ai_verdict) "
            "VALUES (?, ?, ?, ?, ?, 'ek', ?, ?)",
            (eid, ts, host_id, event_type, severity,
             evidence, json.dumps(verdict)),
        )


def _seed_alert(rule_name, host_id, severity="medium",
                 first="2026-07-18 09:00:00", last="2026-07-18 10:00:00"):
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO alerts (host_id, rule_name, severity, title, "
            "first_seen_at, last_seen_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (host_id, rule_name, severity, f"alert {rule_name}",
             first, last),
        )


# ───────────────────────── 单元：IncidentCorrelator.cluster ─────────────────────────
class TestIncidentCorrelatorUnit(IsolatedDBTestCase):
    def test_keyword_mode_groups_by_rule(self):
        hid = _seed_case_host()
        _seed_alert("EternalBlue 利用", hid, severity="high")
        _seed_alert("EternalBlue 利用", hid, severity="high")  # 同名 → 归并为一簇
        _seed_alert("Mimikatz 凭据窃取", hid, severity="critical")
        incidents = asyncio.run(IncidentCorrelator().cluster(
            events=None, mode="keyword", host_id=hid))
        # 两条同规则名 → 1 个 incident；另一条 → 1 个，共 2
        self.assertEqual(len(incidents), 2)
        titles = [i["title"] for i in incidents]
        self.assertTrue(any("EternalBlue" in t for t in titles))
        for inc in incidents:
            self.assertIn("severity", inc)
            self.assertIn("host_ids", inc)
            self.assertIn("alert_ids", inc)
            self.assertIn("kill_chain", inc)
            self.assertIn("alert_count", inc)

    def test_semantic_deterministic_fallback_on_degraded(self):
        """AgentLLM 降级 → 确定性字段聚类并落 incident_clusters。"""
        hid = _seed_case_host()
        # 同 host / 同类型 / 同 ip → 应聚为一簇
        _seed_suspicious_event("SE-1", hid, "lateral_move", ip="1.2.3.4")
        _seed_suspicious_event("SE-2", hid, "lateral_move", ip="1.2.3.4")
        # 不同 ip → 另一簇
        _seed_suspicious_event("SE-3", hid, "lateral_move", ip="9.9.9.9")
        # 非 suspicious 的应被忽略
        _seed_suspicious_event("SE-4", hid, "recon", verdict={"label": "false_positive"})

        with patch("app.services.incident_correlator.AgentLLM") as MockLLM:
            inst = MockLLM.return_value
            inst.call = AsyncMock(return_value={
                "content": "", "degraded": True, "usage": {}, "error": "no profile"})
            clusters = asyncio.run(IncidentCorrelator().cluster(
                mode="semantic", time_window_minutes=BIG_WINDOW))

        self.assertEqual(len(clusters), 2)  # 两簇：1.2.3.4 / 9.9.9.9
        all_members = [mid for c in clusters for mid in c["member_event_ids"]]
        for c in clusters:
            self.assertEqual(c["mode"], "semantic")
            self.assertIn("cluster_id", c)
            self.assertIsInstance(c["member_event_ids"], list)
        # SE-1/SE-2 同簇；SE-3 独立簇；SE-4（非 suspicious）被忽略
        self.assertIn("SE-1", all_members)
        self.assertIn("SE-3", all_members)
        self.assertNotIn("SE-4", all_members)
        # 已落库
        self.assertEqual(IncidentCluster.list()["total"], 2)

    def test_semantic_llm_valid_json_groups(self):
        """AgentLLM 返回合法 JSON → 走语义聚类并按 LLM 分组。"""
        hid = _seed_case_host()
        _seed_suspicious_event("SE-1", hid, "lateral_move", ip="1.2.3.4")
        _seed_suspicious_event("SE-2", hid, "lateral_move", ip="1.2.3.4")
        _seed_suspicious_event("SE-3", hid, "recon", ip="9.9.9.9")
        llm_resp = json.dumps([
            {"title": "横向移动簇", "severity": "high",
             "member_event_ids": ["SE-1", "SE-2"], "summary": "横向"},
            {"title": "侦察簇", "severity": "medium",
             "member_event_ids": ["SE-3"], "summary": "侦察"},
        ])
        with patch("app.services.incident_correlator.AgentLLM") as MockLLM:
            inst = MockLLM.return_value
            inst.call = AsyncMock(return_value={
                "content": llm_resp, "degraded": False, "usage": {}, "error": None})
            clusters = asyncio.run(IncidentCorrelator().cluster(
                mode="semantic", time_window_minutes=BIG_WINDOW))

        self.assertEqual(len(clusters), 2)
        titles = [c["title"] for c in clusters]
        self.assertIn("横向移动簇", titles)
        self.assertIn("侦察簇", titles)
        # 全部落库
        self.assertEqual(IncidentCluster.list()["total"], 2)

    def test_semantic_llm_unparseable_falls_back(self):
        """AgentLLM 返回非 JSON（degraded=False）→ 回退确定性聚类，不抛异常。"""
        hid = _seed_case_host()
        _seed_suspicious_event("SE-1", hid, "lateral_move", ip="1.2.3.4")
        with patch("app.services.incident_correlator.AgentLLM") as MockLLM:
            inst = MockLLM.return_value
            inst.call = AsyncMock(return_value={
                "content": "抱歉我无法处理", "degraded": False,
                "usage": {}, "error": None})
            clusters = asyncio.run(IncidentCorrelator().cluster(
                mode="semantic", time_window_minutes=BIG_WINDOW))
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0]["mode"], "semantic")
        self.assertEqual(IncidentCluster.list()["total"], 1)

    def test_semantic_no_suspicious_returns_empty(self):
        hid = _seed_case_host()
        # 仅 false_positive，无 suspicious
        _seed_suspicious_event("SE-9", hid, "recon",
                               verdict={"label": "false_positive"})
        with patch("app.services.incident_correlator.AgentLLM") as MockLLM:
            inst = MockLLM.return_value
            inst.call = AsyncMock(return_value={"content": "", "degraded": True})
            clusters = asyncio.run(IncidentCorrelator().cluster(
                mode="semantic", time_window_minutes=BIG_WINDOW))
        self.assertEqual(clusters, [])
        self.assertEqual(IncidentCluster.list()["total"], 0)


# ───────────────────────── API：correlate-incidents / incidents/clusters ─────────────────────────
class TestIncidentCorrelatorAPI(IsolatedDBTestCase):
    def setUp(self):
        super().setUp()
        self.client = TestClient(_api_app)
        _api_app.dependency_overrides.clear()

    def tearDown(self):
        _api_app.dependency_overrides.clear()
        super().tearDown()

    def _auth(self, role="admin"):
        user = {"id": 1 if role == "admin" else 2,
                 "username": "admin" if role == "admin" else "analyst",
                 "role": role}
        _api_app.dependency_overrides[get_current_user] = lambda: user

    def test_correlate_no_token_401(self):
        _api_app.dependency_overrides.clear()
        resp = self.client.post("/api/ai/correlate-incidents?mode=semantic")
        self.assertEqual(resp.status_code, 401)

    def test_correlate_keyword_mode_works(self):
        self._auth()
        hid = _seed_case_host()
        _seed_alert("BruteSMB 爆破", hid, severity="high")
        resp = self.client.post("/api/ai/correlate-incidents?mode=keyword")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertEqual(data["mode"], "keyword")
        self.assertGreaterEqual(len(data["incidents"]), 1)

    def test_correlate_semantic_mode_persists_clusters(self):
        self._auth()
        hid = _seed_case_host()
        _seed_suspicious_event("SE-1", hid, "lateral_move", ip="1.2.3.4")
        _seed_suspicious_event("SE-2", hid, "lateral_move", ip="1.2.3.4")
        with patch("app.services.incident_correlator.AgentLLM") as MockLLM:
            inst = MockLLM.return_value
            inst.call = AsyncMock(return_value={"content": "", "degraded": True})
            resp = self.client.post(
                f"/api/ai/correlate-incidents?mode=semantic"
                f"&time_window_minutes={BIG_WINDOW}")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertEqual(data["mode"], "semantic")
        self.assertGreaterEqual(data["total"], 1)
        # 落库检查
        self.assertGreaterEqual(IncidentCluster.list()["total"], 1)

    def test_clusters_no_token_401(self):
        _api_app.dependency_overrides.clear()
        resp = self.client.get("/api/ai/incidents/clusters")
        self.assertEqual(resp.status_code, 401)

    def test_clusters_list_with_filter_and_pagination(self):
        self._auth()
        # 直接落库若干簇
        for i in range(3):
            IncidentCluster.create(title=f"c{i}", severity="critical",
                                 confidence=0.9, member_event_ids=[str(i)],
                                 host_ids=["1"])
        IncidentCluster.create(title="m", severity="medium", confidence=0.5,
                             member_event_ids=["99"], host_ids=["2"])
        # 分页 page_size=2
        r1 = self.client.get("/api/ai/incidents/clusters?page=1&page_size=2")
        self.assertEqual(r1.status_code, 200)
        d1 = r1.json()["data"]
        self.assertEqual(d1["page"], 1)
        self.assertEqual(d1["page_size"], 2)
        self.assertEqual(d1["total"], 4)
        self.assertEqual(len(d1["items"]), 2)
        # severity 过滤
        r2 = self.client.get("/api/ai/incidents/clusters?severity=critical")
        self.assertEqual(r2.status_code, 200)
        d2 = r2.json()["data"]
        self.assertEqual(d2["total"], 3)
        for it in d2["items"]:
            self.assertEqual(it["severity"], "critical")
            self.assertIn("cluster_id", it)
            self.assertIn("member_event_ids", it)


if __name__ == "__main__":
    import unittest
    unittest.main()
