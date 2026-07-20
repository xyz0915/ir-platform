"""AI 事件研判打标 增量自测 + 集成自测 — software-engineer（T-V4）.

覆盖：
- 正常写回 suspicious（键名与消费者逐字符一致）
- 降级（degraded）→ 写 unknown，整批不 500
- 幂等跳过 / force 覆盖
- 批量上限 200 → 端点 400（非 500）
- 阈值降级（confidence < 阈值 的 suspicious → benign）
- 解析失败 → unknown
- 鉴权闸门（无 token → 401，无重复前缀）
- 生产者↔消费者契约：IncidentCorrelator._fetch_suspicious_events 能读到写回数据

安全红线：使用 IsolatedDBTestCase（临时 SQLite），**绝不触碰 backend/data/ir.db**。
"""

import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.auth_service import get_current_user
from app.database import get_connection
from app.services.event_verdict_service import EventVerdictService

from tests._qa_batch1_common import IsolatedDBTestCase


def _now() -> str:
    """当前 UTC 时间字符串（落在消费者 60 分钟时间窗内）."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _safe_json(value):
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None


# ── Fake LLM ────────────────────────────────────────────────────────────────
class _FakeLLMSuspicious:
    """返回合法 suspicious 研判."""

    def __init__(self, *args, **kwargs):
        pass

    async def call(self, prompt, user=None, budget=None):
        return {
            "content": json.dumps({
                "label": "suspicious",
                "confidence": 0.95,
                "reason": "检测到横向移动迹象",
                "attack_type": "横向移动",
            }, ensure_ascii=False),
            "usage": {},
            "degraded": False,
            "error": None,
        }


class _FakeLLMDegraded:
    """模拟无 Profile / 断路器熔断：返回 degraded=True."""

    def __init__(self, *args, **kwargs):
        pass

    async def call(self, prompt, user=None, budget=None):
        return {"content": "", "usage": {}, "degraded": True, "error": "未配置有效的 AI Profile"}


class _FakeLLMLowConfSuspicious:
    """返回 suspicious 但置信度低于默认阈值（应降级为 benign）."""

    def __init__(self, *args, **kwargs):
        pass

    async def call(self, prompt, user=None, budget=None):
        return {
            "content": json.dumps({
                "label": "suspicious",
                "confidence": 0.3,
                "reason": "弱信号，置信度低",
                "attack_type": "",
            }, ensure_ascii=False),
            "usage": {},
            "degraded": False,
            "error": None,
        }


class _FakeLLMBadJson:
    """返回非 JSON 文本（解析失败 → 降级 unknown）."""

    def __init__(self, *args, **kwargs):
        pass

    async def call(self, prompt, user=None, budget=None):
        return {
            "content": "这不是有效的 JSON 乱码文本 ；；；",
            "usage": {},
            "degraded": False,
            "error": None,
        }


# ── 服务层单测 ────────────────────────────────────────────────────────────
class TestEventVerdictService(IsolatedDBTestCase):
    """直接调用 EventVerdictService，覆盖写回/降级/幂等/阈值/解析."""

    def _seed_events(self, n):
        ids = []
        with get_connection() as conn:
            for i in range(1, n + 1):
                eid = f"evt-{i:03d}"
                conn.execute(
                    "INSERT INTO security_events (id, timestamp, host_id, event_type, event_key, evidence) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (eid, _now(), 1, "process_start", f"key-{i}",
                     json.dumps({"process_name": "powershell.exe", "source_ip": "192.168.1.50"})),
                )
                ids.append(eid)
        return ids

    def _verdict(self, eid):
        with get_connection() as conn:
            row = conn.execute(
                "SELECT ai_verdict FROM security_events WHERE id=?", (eid,)
            ).fetchone()
        return _safe_json(row["ai_verdict"]) if row else None

    @patch("app.services.event_verdict_service.AgentLLM", _FakeLLMSuspicious)
    def test_normal_writeback_suspicious(self):
        ids = self._seed_events(3)
        svc = EventVerdictService()
        res = asyncio.run(svc.analyze_events(ids, user={"id": 1}))
        self.assertEqual(res["processed"], 3)
        self.assertEqual(res["skipped"], 0)
        self.assertEqual(res["degraded"], 0)
        self.assertEqual(res["failed"], 0)
        for d in res["details"]:
            self.assertEqual(d["status"], "processed")
            self.assertEqual(d["label"], "suspicious")
        # 消费者查询能命中（键名逐字符一致）
        with get_connection() as conn:
            cnt = conn.execute(
                "SELECT COUNT(*) AS c FROM security_events "
                "WHERE json_extract(ai_verdict,'$.label')='suspicious'"
            ).fetchone()["c"]
            self.assertEqual(cnt, 3)
            v = self._verdict(ids[0])
            self.assertEqual(v["label"], "suspicious")
            self.assertIn("confidence", v)
            self.assertIn("reason", v)
            self.assertIn("attack_type", v)
            self.assertEqual(v["attack_type"], "横向移动")
            # ai_analysis 列已写入（可选列）
            row = conn.execute(
                "SELECT ai_analysis FROM security_events WHERE id=?", (ids[0],)
            ).fetchone()
            self.assertTrue(row["ai_analysis"])

    @patch("app.services.event_verdict_service.AgentLLM", _FakeLLMDegraded)
    def test_degraded_to_unknown(self):
        ids = self._seed_events(2)
        svc = EventVerdictService()
        res = asyncio.run(svc.analyze_events(ids, user={"id": 1}))
        self.assertEqual(res["degraded"], 2)
        self.assertEqual(res["failed"], 0)
        for d in res["details"]:
            self.assertEqual(d["label"], "unknown")
        with get_connection() as conn:
            susp = conn.execute(
                "SELECT COUNT(*) c FROM security_events "
                "WHERE json_extract(ai_verdict,'$.label')='suspicious'"
            ).fetchone()["c"]
            unk = conn.execute(
                "SELECT COUNT(*) c FROM security_events "
                "WHERE json_extract(ai_verdict,'$.label')='unknown'"
            ).fetchone()["c"]
        self.assertEqual(susp, 0)  # 不污染 suspicious
        self.assertEqual(unk, 2)

    @patch("app.services.event_verdict_service.AgentLLM", _FakeLLMSuspicious)
    def test_idempotent_skip_then_force_override(self):
        ids = self._seed_events(2)
        svc = EventVerdictService()
        r1 = asyncio.run(svc.analyze_events(ids, user={"id": 1}, force=False))
        self.assertEqual(r1["processed"], 2)
        # 第二次 force=False → 全部跳过
        r2 = asyncio.run(svc.analyze_events(ids, user={"id": 1}, force=False))
        self.assertEqual(r2["skipped"], 2)
        self.assertEqual(r2["processed"], 0)
        # force=True → 重新研判
        r3 = asyncio.run(svc.analyze_events(ids, user={"id": 1}, force=True))
        self.assertEqual(r3["processed"], 2)
        for d in r3["details"]:
            self.assertEqual(d["status"], "processed")

    @patch("app.services.event_verdict_service.AgentLLM", _FakeLLMLowConfSuspicious)
    def test_threshold_downgrade_to_benign(self):
        ids = self._seed_events(1)
        svc = EventVerdictService()
        # 默认阈值 0.6 > 0.3 → 降级为 benign
        asyncio.run(svc.analyze_events(ids, user={"id": 1}, confidence_threshold=0.6))
        self.assertEqual(self._verdict(ids[0])["label"], "benign")
        # 阈值 0.2 < 0.3 → 保持 suspicious
        asyncio.run(svc.analyze_events(ids, user={"id": 1}, force=True, confidence_threshold=0.2))
        self.assertEqual(self._verdict(ids[0])["label"], "suspicious")

    @patch("app.services.event_verdict_service.AgentLLM", _FakeLLMBadJson)
    def test_parse_failure_to_unknown(self):
        ids = self._seed_events(1)
        svc = EventVerdictService()
        res = asyncio.run(svc.analyze_events(ids, user={"id": 1}))
        self.assertEqual(res["degraded"], 1)
        self.assertEqual(res["details"][0]["label"], "unknown")
        self.assertEqual(self._verdict(ids[0])["label"], "unknown")

    def test_event_not_found_is_failed(self):
        svc = EventVerdictService()
        res = asyncio.run(svc.analyze_events(["nope-999"], user={"id": 1}))
        self.assertEqual(res["failed"], 1)
        self.assertEqual(res["details"][0]["status"], "failed")
        self.assertEqual(res["details"][0]["error"], "event_not_found")

    @patch("app.services.event_verdict_service.AgentLLM", _FakeLLMSuspicious)
    def test_consumer_can_read_producer_output(self):
        """生产者写回键名与 IncidentCorrelator 读取逻辑逐字符一致."""
        ids = self._seed_events(2)
        svc = EventVerdictService()
        asyncio.run(svc.analyze_events(ids, user={"id": 1}, force=True))
        from app.services.incident_correlator import IncidentCorrelator

        susp = IncidentCorrelator()._fetch_suspicious_events(None, 60)
        self.assertEqual(len(susp), 2)
        for e in susp:
            v = _safe_json(e["ai_verdict"])
            self.assertEqual(v["label"], "suspicious")
            self.assertIn("attack_type", v)
            self.assertIn("reason", v)
            self.assertIn("confidence", v)


# ── 端点 / 鉴权 集成测试 ───────────────────────────────────────────────────
class TestEventVerdictEndpoint(IsolatedDBTestCase):
    """通过 TestClient 验证路由挂载、鉴权、上限、重复前缀."""

    def setUp(self):
        super().setUp()
        from app.api import event_verdict as ev_mod

        self.app = FastAPI()
        self.app.include_router(ev_mod.router, prefix="/api/security-events")
        self.admin = {"user_id": 1, "username": "admin", "role": "admin"}
        self.app.dependency_overrides[get_current_user] = lambda: self.admin
        self.client = TestClient(self.app)

    def _seed(self, eids):
        with get_connection() as conn:
            for eid in eids:
                conn.execute(
                    "INSERT INTO security_events (id, timestamp, host_id, event_type, event_key) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (eid, _now(), 1, "process_start", "k"),
                )

    def test_no_duplicate_prefix(self):
        # 正确前缀：路由存在（鉴权已通过，事件不存在 → 200 而非 404）
        r = self.client.post("/api/security-events/ai-verdict", json={"event_ids": ["evt-x"]})
        self.assertNotEqual(r.status_code, 404)
        # 重复前缀必须 404（规避 Batch③ /api/api/... 教训）
        r2 = self.client.post(
            "/api/security-events/security-events/ai-verdict", json={"event_ids": ["evt-x"]}
        )
        self.assertEqual(r2.status_code, 404)

    def test_auth_required_returns_401(self):
        self.app.dependency_overrides.clear()
        r = self.client.post("/api/security-events/ai-verdict", json={"event_ids": ["evt-x"]})
        self.assertEqual(r.status_code, 401)

    @patch("app.services.event_verdict_service.AgentLLM", _FakeLLMSuspicious)
    def test_success_via_endpoint(self):
        self._seed(["evt-x"])
        r = self.client.post("/api/security-events/ai-verdict", json={"event_ids": ["evt-x"]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["code"], 0)
        self.assertEqual(r.json()["data"]["processed"], 1)
        self.assertEqual(r.json()["data"]["details"][0]["label"], "suspicious")

    def test_empty_event_ids_400(self):
        r = self.client.post("/api/security-events/ai-verdict", json={"event_ids": []})
        self.assertEqual(r.status_code, 400)

    def test_batch_limit_400(self):
        ids = [f"evt-{i}" for i in range(201)]
        self._seed(ids)
        r = self.client.post("/api/security-events/ai-verdict", json={"event_ids": ids})
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
