"""AI 事件研判打标（生产者）— 独立 QA 验证套件 — software-qa-engineer（严过关）.

对工程师 software-engineer 交付的「AI 事件研判打标」增量做**独立**验证，覆盖
team-lead 下发的 10 项验证清单：

1.  路由无重复前缀（/api/security-events/ai-verdict）
2.  鉴权闸门（Depends(get_current_user)；无 token → 401）
3.  写回契约（键名/取值与 incident_correlator.py 读取逻辑**逐字符一致**；
    模拟 _fetch_suspicious_events 的 SQL 能查到 suspicious）
4.  降级不 500（degraded/解析失败 → 写 {label:"unknown",...}，整批 2xx）
5.  阈值降级（confidence<阈值 时 suspicious → benign）
6.  幂等（force=False 跳过；force=True 覆盖）
7.  批量上限（>200 → 400，非 500）
8.  参数化写回（UPDATE 用参数化，无 SQL 注入隐患）
9.  前端契约（triggerEventVerdict 路径一致；徽章/按钮；vite build 另跑）
10. 端到端冒烟（mock AgentLLM → 端点 → ai_verdict.label='suspicious' → 消费者命中）

安全红线：使用 ``IsolatedDBTestCase``（临时 SQLite），**绝不触碰 backend/data/ir_platform.db**。
所有 LLM 调用均通过 ``unittest.mock.patch`` 注入 Fake LLM，不触达真实大模型/网络。
"""

import asyncio
import json
import os
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.auth_service import get_current_user
from app.database import get_connection
from app.services.event_verdict_service import EventVerdictService

from tests._qa_batch1_common import IsolatedDBTestCase


# ── 工具 ────────────────────────────────────────────────────────────────────
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


# 消费者读取契约的「黄金」键集合（来自 incident_correlator.py）
CONSUMER_KEYS = {"label", "confidence", "attack_type", "reason"}


# ── Fake LLM ────────────────────────────────────────────────────────────────
class _FakeSuspicious:
    """返回合法 suspicious 研判（4 键齐全）."""

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


class _FakeLowConfSuspicious:
    """返回 suspicious 但置信度低于默认阈值（应降级为 benign）."""

    def __init__(self, *args, **kwargs):
        pass

    async def call(self, prompt, user=None, budget=None):
        return {
            "content": json.dumps({
                "label": "suspicious",
                "confidence": 0.3,
                "reason": "弱信号",
                "attack_type": "",
            }, ensure_ascii=False),
            "usage": {},
            "degraded": False,
            "error": None,
        }


class _FakeDegraded:
    """模拟无 Profile / 断路器熔断：degraded=True."""

    def __init__(self, *args, **kwargs):
        pass

    async def call(self, prompt, user=None, budget=None):
        return {"content": "", "usage": {}, "degraded": True,
                "error": "未配置有效的 AI Profile"}


class _FakeBadJson:
    """返回非 JSON 文本（解析失败 → 写 unknown）."""

    def __init__(self, *args, **kwargs):
        pass

    async def call(self, prompt, user=None, budget=None):
        return {"content": "这不是有效的 JSON 乱码文本 ；；；", "usage": {},
                "degraded": False, "error": None}


class _FakeMaliciousLabel:
    """返回未知 label（应归一化为 unknown）."""

    def __init__(self, *args, **kwargs):
        pass

    async def call(self, prompt, user=None, budget=None):
        return {
            "content": json.dumps({
                "label": "malicious",
                "confidence": 0.9,
                "reason": "未知标签",
                "attack_type": "",
            }, ensure_ascii=False),
            "usage": {}, "degraded": False, "error": None,
        }


class _FakeFencedJson:
    """返回被 ```json 包裹的 JSON（解析应可容忍）."""

    def __init__(self, *args, **kwargs):
        pass

    async def call(self, prompt, user=None, budget=None):
        return {
            "content": (
                "```json\n"
                '{"label": "suspicious", "confidence": 0.88, '
                '"reason": "被包裹的 JSON", "attack_type": "凭据窃取"}\n'
                "```"
            ),
            "usage": {}, "degraded": False, "error": None,
        }


class _FakeOutOfRangeConf:
    """返回越界 confidence（应钳制到 [0,1]）."""

    def __init__(self, *args, **kwargs):
        pass

    async def call(self, prompt, user=None, budget=None):
        return {
            "content": json.dumps({
                "label": "benign",
                "confidence": 1.7,
                "reason": "越界置信度",
                "attack_type": "",
            }, ensure_ascii=False),
            "usage": {}, "degraded": False, "error": None,
        }


# ── T-V1 服务层单测 ────────────────────────────────────────────────────────
class TestEventVerdictServiceQa(IsolatedDBTestCase):
    """直接驱动 EventVerdictService，覆盖写回/降级/幂等/阈值/归一化/防注入."""

    def _seed(self, n, ids=None):
        ids = ids or [f"evt-{i:03d}" for i in range(1, n + 1)]
        with get_connection() as conn:
            for eid in ids:
                conn.execute(
                    "INSERT INTO security_events (id, timestamp, host_id, event_type, event_key, evidence) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (eid, _now(), 1, "process_start", f"key-{eid}",
                     json.dumps({"process_name": "powershell.exe", "source_ip": "192.168.1.50"})),
                )
        return ids

    def _verdict(self, eid):
        with get_connection() as conn:
            row = conn.execute(
                "SELECT ai_verdict FROM security_events WHERE id=?", (eid,)
            ).fetchone()
        return _safe_json(row["ai_verdict"]) if row else None

    # ── 3. 写回契约逐字符一致 ──
    @patch("app.services.event_verdict_service.AgentLLM", _FakeSuspicious)
    def test_writeback_contract_char_by_char(self):
        ids = self._seed(3)
        svc = EventVerdictService()
        res = asyncio.run(svc.analyze_events(ids, user={"id": 1}))
        self.assertEqual(res["processed"], 3)
        for eid in ids:
            v = self._verdict(eid)
            self.assertIsNotNone(v)
            # 键集合必须与消费者读取键逐字符一致（不多不少）
            self.assertEqual(set(v.keys()), CONSUMER_KEYS)
            self.assertEqual(v["label"], "suspicious")
            self.assertIsInstance(v["confidence"], float)
            self.assertGreaterEqual(v["confidence"], 0.0)
            self.assertLessEqual(v["confidence"], 1.0)
            self.assertEqual(v["attack_type"], "横向移动")
            self.assertTrue(v["reason"])

    # ── 4. 降级不 500（degraded → unknown，整批 2xx）──
    @patch("app.services.event_verdict_service.AgentLLM", _FakeDegraded)
    def test_degraded_to_unknown_no_500(self):
        ids = self._seed(2)
        svc = EventVerdictService()
        res = asyncio.run(svc.analyze_events(ids, user={"id": 1}))
        self.assertEqual(res["degraded"], 2)
        self.assertEqual(res["failed"], 0)
        self.assertEqual(res["processed"], 0)
        for d in res["details"]:
            self.assertEqual(d["status"], "degraded")
            self.assertEqual(d["label"], "unknown")
        # 降级事件不应污染 suspicious 统计
        with get_connection() as conn:
            susp = conn.execute(
                "SELECT COUNT(*) c FROM security_events "
                "WHERE json_extract(ai_verdict,'$.label')='suspicious'"
            ).fetchone()["c"]
            unk = conn.execute(
                "SELECT COUNT(*) c FROM security_events "
                "WHERE json_extract(ai_verdict,'$.label')='unknown'"
            ).fetchone()["c"]
        self.assertEqual(susp, 0)
        self.assertEqual(unk, 2)

    # ── 4b. 解析失败 → unknown ──
    @patch("app.services.event_verdict_service.AgentLLM", _FakeBadJson)
    def test_parse_failure_to_unknown(self):
        ids = self._seed(1)
        svc = EventVerdictService()
        res = asyncio.run(svc.analyze_events(ids, user={"id": 1}))
        self.assertEqual(res["degraded"], 1)
        self.assertEqual(res["failed"], 0)
        self.assertEqual(self._verdict(ids[0])["label"], "unknown")

    # ── 5. 阈值降级 ──
    @patch("app.services.event_verdict_service.AgentLLM", _FakeLowConfSuspicious)
    def test_threshold_downgrade(self):
        ids = self._seed(1)
        svc = EventVerdictService()
        # 默认阈值 0.6 > 0.3 → benign
        asyncio.run(svc.analyze_events(ids, user={"id": 1}, confidence_threshold=0.6))
        self.assertEqual(self._verdict(ids[0])["label"], "benign")
        # 阈值 0.2 < 0.3 → 仍 suspicious
        asyncio.run(svc.analyze_events(ids, user={"id": 1}, force=True, confidence_threshold=0.2))
        self.assertEqual(self._verdict(ids[0])["label"], "suspicious")

    # ── 6. 幂等：force=False 跳过；force=True 覆盖 ──
    @patch("app.services.event_verdict_service.AgentLLM", _FakeSuspicious)
    def test_idempotent_skip_and_force(self):
        ids = self._seed(2)
        svc = EventVerdictService()
        r1 = asyncio.run(svc.analyze_events(ids, user={"id": 1}, force=False))
        self.assertEqual(r1["processed"], 2)
        self.assertEqual(r1["skipped"], 0)
        # 再跑 force=False → 全部跳过
        r2 = asyncio.run(svc.analyze_events(ids, user={"id": 1}, force=False))
        self.assertEqual(r2["skipped"], 2)
        self.assertEqual(r2["processed"], 0)
        # force=True → 重新研判
        r3 = asyncio.run(svc.analyze_events(ids, user={"id": 1}, force=True))
        self.assertEqual(r3["processed"], 2)
        for d in r3["details"]:
            self.assertEqual(d["status"], "processed")

    # ── 未知 label 归一化为 unknown ──
    @patch("app.services.event_verdict_service.AgentLLM", _FakeMaliciousLabel)
    def test_unknown_label_normalized(self):
        ids = self._seed(1)
        svc = EventVerdictService()
        asyncio.run(svc.analyze_events(ids, user={"id": 1}))
        self.assertEqual(self._verdict(ids[0])["label"], "unknown")

    # ── confidence 越界钳制 ──
    @patch("app.services.event_verdict_service.AgentLLM", _FakeOutOfRangeConf)
    def test_confidence_clamped(self):
        ids = self._seed(1)
        svc = EventVerdictService()
        asyncio.run(svc.analyze_events(ids, user={"id": 1}))
        self.assertAlmostEqual(self._verdict(ids[0])["confidence"], 1.0, places=3)

    # ── 容忍 ```json 包裹 ──
    @patch("app.services.event_verdict_service.AgentLLM", _FakeFencedJson)
    def test_fenced_json_tolerated(self):
        ids = self._seed(1)
        svc = EventVerdictService()
        res = asyncio.run(svc.analyze_events(ids, user={"id": 1}))
        self.assertEqual(res["processed"], 1)
        v = self._verdict(ids[0])
        self.assertEqual(v["label"], "suspicious")
        self.assertEqual(v["attack_type"], "凭据窃取")

    # ── 事件不存在 → failed（不抛）──
    def test_event_not_found_failed(self):
        svc = EventVerdictService()
        res = asyncio.run(svc.analyze_events(["nope-999"], user={"id": 1}))
        self.assertEqual(res["failed"], 1)
        self.assertEqual(res["details"][0]["status"], "failed")
        self.assertEqual(res["details"][0]["error"], "event_not_found")

    # ── 8. 参数化写回防注入 ──
    @patch("app.services.event_verdict_service.AgentLLM", _FakeSuspicious)
    def test_parameterized_writeback_no_injection(self):
        # 普通事件
        normal = self._seed(2)
        # 一个「恶意」id：若 WHERE 被字符串拼接，会匹配所有行
        tricky = "evt-1' OR '1'='1"
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO security_events (id, timestamp, host_id, event_type, event_key, evidence) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (tricky, _now(), 1, "process_start", "k-tricky",
                 json.dumps({"process_name": "x.exe"})),
            )
        svc = EventVerdictService()
        res = asyncio.run(svc.analyze_events([tricky], user={"id": 1}))
        self.assertEqual(res["processed"], 1)
        # 仅 tricky 行被写回
        self.assertEqual(self._verdict(tricky)["label"], "suspicious")
        # 普通行保持未被研判（证明 WHERE 是参数化，未注入影响全部行）
        for eid in normal:
            self.assertEqual(self._verdict(eid), {})

    # ── 响应结构 5 字段齐全，limit=200 ──
    @patch("app.services.event_verdict_service.AgentLLM", _FakeSuspicious)
    def test_response_shape(self):
        ids = self._seed(1)
        svc = EventVerdictService()
        res = asyncio.run(svc.analyze_events(ids, user={"id": 1}))
        for k in ("processed", "skipped", "degraded", "failed", "limit", "details"):
            self.assertIn(k, res)
        self.assertEqual(res["limit"], EventVerdictService.MAX_BATCH)
        self.assertEqual(len(res["details"]), 1)
        self.assertIn("event_id", res["details"][0])
        self.assertIn("status", res["details"][0])


# ── T-V2 端点 / 鉴权 集成测试 ───────────────────────────────────────────────
class TestEventVerdictEndpointQa(IsolatedDBTestCase):
    """通过 TestClient 验证路由挂载、鉴权、上限、重复前缀、响应包裹."""

    def setUp(self):
        super().setUp()
        from app.api import event_verdict as ev_mod

        self.app = FastAPI()
        self.app.include_router(ev_mod.router, prefix="/api/security-events")
        self.admin = {"user_id": 1, "username": "admin", "role": "admin"}
        self.app.dependency_overrides[get_current_user] = lambda: self.admin
        self.client = TestClient(self.app)

    def _seed(self, ids):
        with get_connection() as conn:
            for eid in ids:
                conn.execute(
                    "INSERT INTO security_events (id, timestamp, host_id, event_type, event_key) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (eid, _now(), 1, "process_start", "k"),
                )

    # ── 1. 路由无重复前缀 ──
    def test_no_duplicate_prefix(self):
        r = self.client.post("/api/security-events/ai-verdict",
                              json={"event_ids": ["evt-x"]})
        self.assertNotEqual(r.status_code, 404)  # 正确路径可达（401 之外均为 2xx）
        r2 = self.client.post("/api/security-events/security-events/ai-verdict",
                               json={"event_ids": ["evt-x"]})
        self.assertEqual(r2.status_code, 404)  # 重复前缀必须 404

    # ── 2. 鉴权闸门：无 token → 401 ──
    def test_auth_required_401(self):
        self.app.dependency_overrides.clear()
        r = self.client.post("/api/security-events/ai-verdict",
                              json={"event_ids": ["evt-x"]})
        self.assertEqual(r.status_code, 401)

    # ── 端点成功写回 suspicious ──
    @patch("app.services.event_verdict_service.AgentLLM", _FakeSuspicious)
    def test_success_via_endpoint(self):
        self._seed(["evt-x"])
        r = self.client.post("/api/security-events/ai-verdict",
                              json={"event_ids": ["evt-x"]})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["code"], 0)
        self.assertEqual(body["message"], "success")
        self.assertEqual(body["data"]["processed"], 1)
        self.assertEqual(body["data"]["details"][0]["label"], "suspicious")

    # ── 空 event_ids → 400 ──
    def test_empty_event_ids_400(self):
        r = self.client.post("/api/security-events/ai-verdict",
                              json={"event_ids": []})
        self.assertEqual(r.status_code, 400)

    # ── 7. 批量上限 >200 → 400（非 500）──
    def test_batch_limit_400(self):
        ids = [f"evt-{i}" for i in range(201)]
        self._seed(ids)
        r = self.client.post("/api/security-events/ai-verdict",
                              json={"event_ids": ids})
        self.assertEqual(r.status_code, 400)

    # ── 边界：恰好 200 条允许（不 400）──
    @patch("app.services.event_verdict_service.AgentLLM", _FakeSuspicious)
    def test_batch_limit_exact_200_ok(self):
        ids = [f"evt-{i:03d}" for i in range(200)]
        self._seed(ids)
        r = self.client.post("/api/security-events/ai-verdict",
                              json={"event_ids": ids})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["data"]["processed"], 200)


# ── 3 / 10. 生产者↔消费者契约 + 端到端冒烟 ──────────────────────────────────
class TestProducerConsumerContractQa(IsolatedDBTestCase):
    """验证生产者写回能被 IncidentCorrelator 消费者真正读到（链路打通）."""

    def _seed(self, n, ids=None):
        ids = ids or [f"evt-{i:03d}" for i in range(1, n + 1)]
        with get_connection() as conn:
            for eid in ids:
                conn.execute(
                    "INSERT INTO security_events (id, timestamp, host_id, event_type, event_key, evidence) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (eid, _now(), 1, "process_start", f"key-{eid}",
                     json.dumps({"process_name": "powershell.exe"})),
                )
        return ids

    @patch("app.services.event_verdict_service.AgentLLM", _FakeSuspicious)
    def test_consumer_fetches_producer_output(self):
        """生产者写回键名与 IncidentCorrelator 读取逻辑逐字符一致."""
        ids = self._seed(2)
        svc = EventVerdictService()
        asyncio.run(svc.analyze_events(ids, user={"id": 1}, force=True))
        from app.services.incident_correlator import IncidentCorrelator

        susp = IncidentCorrelator()._fetch_suspicious_events(None, 60)
        self.assertEqual(len(susp), 2)
        for e in susp:
            v = _safe_json(e["ai_verdict"])
            self.assertEqual(v["label"], "suspicious")
            for k in CONSUMER_KEYS:
                self.assertIn(k, v)

    @patch("app.services.event_verdict_service.AgentLLM", _FakeSuspicious)
    def test_consumer_aggregators_read_keys(self):
        """验证 _verdict_agg / _cluster_confidence 能消费生产者输出."""
        ids = self._seed(1)
        svc = EventVerdictService()
        asyncio.run(svc.analyze_events(ids, user={"id": 1}, force=True))
        from app.services.incident_correlator import IncidentCorrelator

        rows = IncidentCorrelator()._fetch_suspicious_events(None, 60)
        # 静态聚合器：member_ids 取所有成员
        member_ids = [str(r["id"]) for r in rows]
        agg = IncidentCorrelator._verdict_agg(rows, member_ids)
        # 消费者按 verdict.get("label") 聚合 → labels 含 suspicious
        self.assertIn("suspicious", agg["labels"])
        self.assertEqual(agg["labels"]["suspicious"], 1)
        # 消费者按 verdict.get("attack_type") 聚合 → attack_types 含具体攻击类型
        self.assertIn("横向移动", agg["attack_types"])
        # 消费者按 verdict.get("confidence") 聚合 → avg_confidence 正确
        self.assertAlmostEqual(agg["avg_confidence"], 0.95, places=2)
        conf = IncidentCorrelator._cluster_confidence(rows, member_ids)
        self.assertIsInstance(conf, float)
        self.assertGreater(conf, 0.0)

    @patch("app.services.event_verdict_service.AgentLLM", _FakeSuspicious)
    def test_e2e_smoke_endpoint_to_consumer(self):
        """端到端：mock LLM → 端点 → ai_verdict.label='suspicious' → 消费者命中."""
        self._seed(1, ids=["evt-smoke"])
        app = FastAPI()
        from app.api import event_verdict as ev_mod
        app.include_router(ev_mod.router, prefix="/api/security-events")
        app.dependency_overrides[get_current_user] = (
            lambda: {"user_id": 1, "username": "admin", "role": "admin"}
        )
        client = TestClient(app)
        r = client.post("/api/security-events/ai-verdict",
                        json={"event_ids": ["evt-smoke"]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["data"]["details"][0]["label"], "suspicious")

        from app.services.incident_correlator import IncidentCorrelator

        susp = IncidentCorrelator()._fetch_suspicious_events(None, 60)
        self.assertEqual(len(susp), 1)
        self.assertEqual(_safe_json(susp[0]["ai_verdict"])["label"], "suspicious")


# ── 9. 前端契约（静态校验源文件；vite build 另由 Bash 单独验证）──────────────
class TestFrontendContractQa(unittest.TestCase):
    """校验前端 source 与后端契约一致（路径/徽章/按钮）。不依赖 node 运行时."""

    FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "src"

    def _read(self, rel):
        p = self.FRONTEND / rel
        self.assertTrue(p.exists(), f"缺少前端文件: {p}")
        return p.read_text(encoding="utf-8")

    def test_triggerEventVerdict_path_matches_backend(self):
        src = self._read("api/events.js")
        # 请求路径（baseURL=/api 拼接后为 /api/security-events/ai-verdict）
        self.assertIn("request.post('/security-events/ai-verdict'", src)
        self.assertIn("triggerEventVerdict", src)
        # 透传 force / confidence_threshold
        self.assertIn("confidence_threshold", src)

    def test_EventDetailPanel_badge_and_attack_type(self):
        src = self._read("components/analysis/EventDetailPanel.vue")
        # 按 label 上色的徽章类
        self.assertIn("verdict-badge", src)
        self.assertIn("vlabel-suspicious", src)
        self.assertIn("vlabel-benign", src)
        self.assertIn("vlabel-false_positive", src)
        self.assertIn("vlabel-unknown", src)
        # 展示 attack_type
        self.assertIn("aiAttackType", src)
        self.assertIn("attack_type", src)

    def test_AnalysisCenterView_has_button(self):
        src = self._read("views/AnalysisCenterView.vue")
        self.assertIn("AI 研判打标", src)
        self.assertIn("analyzeEvents", src)
        self.assertIn("selectedEventIds", src)


if __name__ == "__main__":
    unittest.main()
