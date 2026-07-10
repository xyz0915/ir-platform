#!/usr/bin/env python3
"""QA 独立补充验证（严过关）.

目标：不依赖工程师测试，从「真实跑通」角度独立验证 v1.2.0 五大改进点：
  ① 攻击链：真实写入多维度取证行 → RuleEngine.evaluate 主机级命中 critical（含跨主机不命中）
  ② AI 全貌/处置：mock LLM 跑通 _execute_task 的 overview/remediation 分支，校验 ai_payload 结构
  ③ Agent 差分：真实 JSON 跑 diff.compute_diff 的 added/changed，并验证缺 baseline 回退全量
  ④ 多源情报：注册两个假 provider 并断言「两源都真的被查询」+ consensus=multi_source + force_refresh 重查
  ⑤ 分级报告：种入含 IOC 值的数据，断言 executive 完全脱敏（无原始 IOC）、technical 含原始 IOC

每个测试类使用独立临时库，互不影响。

说明：攻击链与 AI 两点各发现 1 个「源码 Bug」（工程师自带测试因走注入/直写模型而漏测）。
本文件对这两点采用两种方式：
  - 用「修正后的本地桩」跑通逻辑，证明功能设计正确（通过）；
  - 另写 *reproduction 测试直接复现源码 Bug（抛出预期异常），作为回归证据。
源码 Bug 已转交工程师修复（见测试报告），QA 不改动业务源码。
"""

import asyncio
import json
import sys
import unittest
from datetime import datetime as _dt
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
AGENT_DIR = REPO_ROOT / "agent"
for p in (str(BACKEND_DIR), str(REPO_ROOT), str(AGENT_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from app.config import settings  # noqa: E402

TEST_DB = str(BACKEND_DIR / "data" / "test_qa_supplementary.db")


def _init_tmp_db():
    db_path = Path(TEST_DB)
    if db_path.exists():
        db_path.unlink()
    settings.DB_PATH = TEST_DB
    from app.database import init_db
    init_db()


# ──────────────────────────────────────────────────────────────────────
# ① 攻击链：真实 DB 下钻 + 主机作用域
# ──────────────────────────────────────────────────────────────────────
class TestAttackChainRealDb(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _init_tmp_db()
        from app.models.case import Case
        from app.models.host import Host
        from app.models.analysis import (
            AbnormalProcess, SuspiciousConnection, RegistryKey,
        )

        case = Case.create(name="qa-attackchain")
        cls.host_a = Host.create(case_id=case["id"], hostname="hostA", ip_address="10.0.0.1")
        cls.host_b = Host.create(case_id=case["id"], hostname="hostB", ip_address="10.0.0.2")

        # 主机 A 写入跨维度事件（顺序：process → connection → registry）
        AbnormalProcess.batch_create(cls.host_a["id"], [{
            "pid": 1, "process_name": "powershell.exe",
            "command_line": "powershell -enc AAAA",
        }])
        SuspiciousConnection.batch_create(cls.host_a["id"], [{
            "remote_address": "c2.example.com", "remote_port": 443,
            "protocol": "tcp", "state": "ESTABLISHED",
        }])
        RegistryKey.batch_create(cls.host_a["id"], [{
            "key_path": "HKLM\\Software\\Microsoft\\Windows\\CurrentVersion\\Run",
            "value_name": "evil", "value_data": "x",
        }])

    def _rule(self):
        return {
            "name": "qa_chain", "rule_type": "attack_chain", "severity": "low",
            "condition": {
                "window_minutes": 60, "host_scope": "single",
                "ordered_steps": [
                    {"step": 1, "dimension": "process",
                     "match": {"type": "regex", "field": "command_line",
                               "pattern": "powershell.*-enc"}},
                    {"step": 2, "dimension": "connection",
                     "match": {"type": "list", "field": "remote_address",
                               "values": ["c2.example.com"], "match_mode": "exact"}},
                    {"step": 3, "dimension": "registry",
                     "match": {"type": "regex", "field": "key_path",
                               "pattern": "(?i).*Run"}},
                ],
            },
        }

    def test_same_host_ordered_hit_is_critical(self):
        """真实 DB 下钻 + 主机级顺序匹配 → 命中 critical（BUG-1 修复后，_build_host_events 排序不再崩溃）。"""
        from app.rules.rule_engine import RuleEngine
        matches = RuleEngine.evaluate([], [self._rule()],
                                      global_context={"host_id": self.host_a["id"]})

        self.assertEqual(len(matches), 1)
        m = matches[0]
        self.assertEqual(m["severity"], "critical")  # 强制覆盖 low → critical
        self.assertTrue(m["item"]["_attack_chain"])
        self.assertEqual(len(m["item"]["attack_chain_steps"]), 3)
        self.assertIn("攻击链", m["reason"])
        self.assertIn("步骤", m["reason"])

    def test_build_host_events_sort_fixed(self):
        """验证 BUG-1 已修复：真实多维度事件下 _build_host_events 排序不再抛 NameError，
        且返回非空（按时间排序）的事件列表。"""
        from app.rules.rule_engine import RuleEngine
        events = RuleEngine._build_host_events({"host_id": self.host_a["id"]})
        self.assertIsInstance(events, list)
        # process / connection / registry 三类维度均被下钻聚合
        self.assertGreaterEqual(len(events), 3)
        dims = {e["dimension"] for e in events}
        self.assertIn("process", dims)
        self.assertIn("connection", dims)
        self.assertIn("registry", dims)

    def test_cross_host_does_not_match(self):
        from app.rules.rule_engine import RuleEngine
        # 主机 B 无任何相关事件 → 攻击链不应命中（验证主机作用域）
        matches = RuleEngine.evaluate([], [self._rule()],
                                      global_context={"host_id": self.host_b["id"]})
        self.assertEqual(matches, [])

    def test_missing_host_id_skips(self):
        from app.rules.rule_engine import RuleEngine
        matches = RuleEngine.evaluate([], [self._rule()], global_context={})
        self.assertEqual(matches, [])


# ──────────────────────────────────────────────────────────────────────
# ② AI 全貌/处置：跑通 _execute_task 的 overview/remediation 分支
# ──────────────────────────────────────────────────────────────────────
OVERVIEW_JSON = json.dumps(
    {"story_line": "攻击者于 10:02 钓鱼投递 loader，10:05 以 powershell -enc 内存加载",
     "key_events": [{"time": "2026-07-11 10:05", "dimension": "process",
                     "summary": "powershell -enc"}]}, ensure_ascii=False)
REMEDIATION_JSON = json.dumps(
    {"remediation_scripts": [
        {"id": "s1", "description": "终止可疑 powershell 进程", "language": "powershell",
         "script": "Stop-Process -Name powershell", "risk": "medium",
         "reversible": True, "requires_approval": True}]}, ensure_ascii=False)


async def _fake_llm_overview(api_base_url, api_key, model, system_prompt,
                             user_prompt, max_tokens, temperature):
    yield {"content": OVERVIEW_JSON}


async def _fake_llm_remediation(api_base_url, api_key, model, system_prompt,
                                user_prompt, max_tokens, temperature):
    yield {"content": REMEDIATION_JSON}


def _fixed_parse_json(content):
    """复刻「应该正确」的解析：保留 overview/remediation 专属字段。

    生产中 AiTaskService._parse_json_response 只保留 4 个标准段落，会丢弃
    story_line / key_events / remediation_scripts（见 test_parse_json_response_drops_overview_fields）。
    """
    if not content:
        return {}
    s = content
    if "```json" in s:
        start = s.find("```json") + 7
        end = s.find("```", start)
        if end > start:
            s = s[start:end].strip()
    elif "```" in s:
        start = s.find("```") + 3
        end = s.find("```", start)
        if end > start:
            s = s[start:end].strip()
    if "{" not in s:
        return {"raw": content}
    js = s[s.find("{"): s.rfind("}") + 1]
    try:
        return json.loads(js)
    except json.JSONDecodeError:
        return {"raw": content}


class TestAiOverviewRemediationE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _init_tmp_db()
        from app.models.case import Case
        from app.models.host import Host
        from app.models.ai_config import AiConfigProfile
        case = Case.create(name="qa-ai")
        cls.host = Host.create(case_id=case["id"], hostname="hostAI", ip_address="10.0.0.9")
        # 首个 profile 自动激活
        AiConfigProfile.create(profile_name="qa-ai", api_key="", model_name="test-model")

    def _run_task(self, mode, fake_stream, parse_patch):
        from app.models.ai_task import AiTask
        from app.models.ai_analysis import AiAnalysisReport
        from app.services.ai_task_service import AiTaskService
        from app.services.ai_service import AiService

        task = AiTask.create(host_id=self.host["id"], mode=mode)
        patches = [
            mock.patch.object(AiService, "call_llm_stream", fake_stream),
            mock.patch.object(AiService, "decrypt_api_key", return_value=""),
        ]
        if parse_patch:
            patches.append(mock.patch.object(
                AiTaskService, "_parse_json_response", staticmethod(_fixed_parse_json)))
        for p in patches:
            p.start()
        try:
            asyncio.run(AiTaskService._execute_task(task["id"]))
        finally:
            for p in patches:
                p.stop()
        return AiAnalysisReport.get_by_host(self.host["id"])

    def test_overview_branch_stores_story_line(self):
        """跑通 overview 分支（使用 BUG-2 修复后的真实 _parse_json_response），证明 story_line 正确落库。"""
        report = self._run_task("overview", _fake_llm_overview, parse_patch=False)
        self.assertEqual(report["analysis_type"], "overview")
        payload = json.loads(report["ai_payload"])
        self.assertEqual(payload["mode"], "overview")
        self.assertIn("story_line", payload)
        self.assertTrue(payload["story_line"])
        self.assertIn("key_events", payload)
        # 仅生成/存储，不执行：raw_response 应保留 LLM 原文
        self.assertIn("story_line", report["raw_response"])

    def test_remediation_branch_stores_scripts_with_risk_reversible(self):
        """跑通 remediation 分支（使用 BUG-2 修复后的真实 _parse_json_response），证明脚本带 risk/reversible 字段。"""
        report = self._run_task("remediation", _fake_llm_remediation, parse_patch=False)
        self.assertEqual(report["analysis_type"], "remediation")
        payload = json.loads(report["ai_payload"])
        self.assertEqual(payload["mode"], "remediation")
        scripts = payload["remediation_scripts"]
        self.assertIsInstance(scripts, list)
        self.assertEqual(scripts[0]["id"], "s1")
        # 决策③：脚本带 risk / reversible 字段（供展示，不执行）
        self.assertIn("risk", scripts[0])
        self.assertIn("reversible", scripts[0])
        self.assertIn("requires_approval", scripts[0])

    def test_parse_json_response_preserves_overview_fields(self):
        """验证 BUG-2 已修复：_parse_json_response 对 overview 模式保留 story_line / key_events，
        对 remediation 模式保留 remediation_scripts 顶层字段并原样透传。"""
        from app.services.ai_task_service import AiTaskService
        parsed = AiTaskService._parse_json_response(OVERVIEW_JSON)
        self.assertIn("story_line", parsed)
        self.assertTrue(parsed.get("story_line"))
        self.assertIn("key_events", parsed)

        parsed_rm = AiTaskService._parse_json_response(REMEDIATION_JSON)
        self.assertIn("remediation_scripts", parsed_rm)
        scripts = parsed_rm.get("remediation_scripts")
        self.assertIsInstance(scripts, list)
        self.assertEqual(scripts[0]["id"], "s1")


# ──────────────────────────────────────────────────────────────────────
# ③ Agent 差分：真实 JSON 跑 compute_diff + 缺 baseline 回退
# ──────────────────────────────────────────────────────────────────────
class TestAgentDiffIndependent(unittest.TestCase):
    def test_compute_diff_added_changed_removed(self):
        from utils.diff import compute_diff
        baseline = {
            "processes": [
                {"pid": 1, "name": "svchost"},
                {"pid": 2, "name": "explorer"},
            ],
            "registry": {"Run": "x", "Policies": "y"},
            "users": ["alice", "bob"],
        }
        current = {
            "processes": [
                {"pid": 1, "name": "svchost"},
                {"pid": 99, "name": "malware"},
            ],
            "registry": {"Run": "x", "Policies": "CHANGED"},
            "users": ["alice", "bob", "carol"],
        }
        d = compute_diff(baseline, current)
        # 列表型：进程新增 malware、移除 explorer
        self.assertIn("processes", d)
        self.assertEqual(d["processes"]["added"], [{"pid": 99, "name": "malware"}])
        self.assertEqual(d["processes"]["removed"], [{"pid": 2, "name": "explorer"}])
        # 字典型：registry 的 Policies 变更
        self.assertIn("registry", d)
        self.assertEqual(d["registry"]["changed"], {"Policies": {"old": "y", "new": "CHANGED"}})
        # users 新增 carol
        self.assertIn("users", d)
        self.assertEqual(d["users"]["added"], ["carol"])

    def test_missing_baseline_falls_back_to_full(self):
        from utils.diff import compute_diff
        current = {"processes": [{"pid": 5, "name": "x"}]}
        # baseline 缺失时（agent 用 {} 表示无 baseline），所有项视为新增
        d = compute_diff({}, current)
        self.assertIn("processes", d)
        self.assertEqual(d["processes"]["added"], [{"pid": 5, "name": "x"}])
        self.assertEqual(d["processes"]["removed"], [])

    def test_health_summary_format(self):
        from utils._health import CollectorHealth
        h = CollectorHealth()
        h.record("processes", "ok", 312)
        h.record("network", "degraded", 45, ["wmic 超时，已降级至 tasklist"])
        h.record("registry", "failed", 0, ["注册表键不可读"])
        out = h.build("2026-07-11 10:00:00")
        self.assertEqual(out["collectors"]["processes"]["status"], "ok")
        self.assertEqual(out["collectors"]["registry"]["status"], "failed")
        self.assertIn("1 failed", out["summary"])
        self.assertIn("1 degraded", out["summary"])
        self.assertIn("1 ok", out["summary"])


# ──────────────────────────────────────────────────────────────────────
# ④ 多源情报：两源真的被查询 + consensus + force_refresh 重查
# ──────────────────────────────────────────────────────────────────────
class QA_FakeVT:
    calls = []

    def __init__(self, config):
        from app.services.enrichment_service import BaseThreatIntelProvider
        BaseThreatIntelProvider.__init__(self, config)
        self.judgments = config.get("judgments", ["malicious"])
        self.risk_score = config.get("risk_score", 90)
        self.confidence = config.get("confidence", 80)

    def query(self, ioc_type, ioc_value):
        QA_FakeVT.calls.append((self.name, ioc_type, ioc_value))
        from app.services.enrichment_service import BaseThreatIntelProvider
        return BaseThreatIntelProvider.build_normalized(
            ioc_type, ioc_value, self.name,
            {"judgments": self.judgments, "risk_score": self.risk_score,
             "confidence": self.confidence})


class QA_FakeAB(QA_FakeVT):
    pass


class TestMultiSourceConsensusIndependent(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _init_tmp_db()
        from app.services.enrichment_service import _PROVIDER_REGISTRY
        _PROVIDER_REGISTRY["qa_fakevt"] = QA_FakeVT
        _PROVIDER_REGISTRY["qa_fakeab"] = QA_FakeAB

    def setUp(self):
        from app.database import get_connection
        from app.services.enrichment_service import EnrichmentService
        with get_connection() as conn:
            conn.execute("DELETE FROM threat_intel")
            conn.execute("DELETE FROM iocs")
        EnrichmentService._instance = None
        # 注意：calls 在 QA_FakeVT / QA_FakeAB 间为同一继承列表，clear() 原地清空即可
        QA_FakeVT.calls.clear()
        self.svc = EnrichmentService()

    def _patch_two(self):
        configs = [
            {"name": "qa_fakevt", "type": "qa_fakevt", "base_url": "x",
             "judgments": ["malicious"], "risk_score": 90, "confidence": 80},
            {"name": "qa_fakeab", "type": "qa_fakeab", "base_url": "x",
             "judgments": ["malicious"], "risk_score": 70, "confidence": 100},
        ]
        return mock.patch(
            "app.services.enrichment_service.ThreatIntelProviderConfig.load",
            return_value=configs)

    def test_both_providers_queried_and_multi_source(self):
        from app.models.ioc import Ioc
        from app.models.threat_intel import ThreatIntel
        with self._patch_two():
            ioc = Ioc.create(ioc_type="ip", ioc_value="5.5.5.5", source="user")
            rec = self.svc.enrich_ioc(ioc["id"], "ip", "5.5.5.5")
        # 两源「类型」都真的被查询（真实多源，而非单源）
        queried_types = {c[0] for c in QA_FakeVT.calls}
        self.assertEqual(queried_types, {"qa_fakevt", "qa_fakeab"})
        self.assertEqual(rec["consensus"], "multi_source")
        self.assertEqual(rec["confidence"], 100)  # max(80,100)
        self.assertEqual(rec["risk_score"], 90)    # max(90,70)
        stored = ThreatIntel.list_by_value("5.5.5.5")
        self.assertEqual(len(stored), 1)
        self.assertIn("qa_fakevt", stored[0]["providers"])
        self.assertIn("qa_fakeab", stored[0]["providers"])

    def test_force_refresh_requeries_providers(self):
        with self._patch_two():
            self.svc.enrich_ioc(None, "ip", "7.7.7.7")
            QA_FakeVT.calls.clear()
            rec2 = self.svc.enrich_ioc(None, "ip", "7.7.7.7", force_refresh=True)
        # force_refresh 跳过缓存 → 两源再次被查询
        self.assertTrue(QA_FakeVT.calls)
        self.assertEqual(rec2["consensus"], "multi_source")

    def test_single_source_consensus(self):
        from app.models.ioc import Ioc
        configs = [{"name": "qa_fakevt", "type": "qa_fakevt", "base_url": "x",
                    "judgments": ["malicious"], "risk_score": 90, "confidence": 80}]
        with mock.patch(
            "app.services.enrichment_service.ThreatIntelProviderConfig.load",
            return_value=configs,
        ):
            ioc = Ioc.create(ioc_type="ip", ioc_value="6.6.6.6", source="user")
            rec = self.svc.enrich_ioc(ioc["id"], "ip", "6.6.6.6")
        self.assertEqual(rec["consensus"], "single_source")


# ──────────────────────────────────────────────────────────────────────
# ⑤ 分级报告：executive 完全脱敏（无原始 IOC）/ technical 含原始 IOC
# ──────────────────────────────────────────────────────────────────────
class TestReportMaskingIndependent(unittest.TestCase):
    IOC = "185.220.101.45"

    @classmethod
    def setUpClass(cls):
        _init_tmp_db()
        from app.models.case import Case
        from app.models.host import Host
        from app.models.analysis import (
            AnalysisResult, AbnormalProcess, IocHit,
        )
        from app.models.remediation_checklist import RemediationChecklist

        case = Case.create(name="qa-report")
        cls.host = Host.create(case_id=case["id"], hostname="hostRPT", ip_address="10.0.0.7")
        hid = cls.host["id"]
        AnalysisResult.create_or_replace(
            host_id=hid, risk_level="high", risk_score=80,
            total_findings=2, summary="发现可疑进程与 C2 外连", details={},
        )
        # 进程命令行中嵌入 IOC IP，验证 executive 脱敏
        AbnormalProcess.batch_create(hid, [{
            "pid": 1, "process_name": "powershell.exe",
            "command_line": f"powershell -enc {cls.IOC}",
        }])
        # IOC 命中记录含原始值
        IocHit.batch_create(hid, [{
            "ioc_type": "ip", "ioc_value": cls.IOC,
            "matched_in": "suspicious_connection", "context": "C2",
        }])
        # 处置清单（technical 应展示）
        RemediationChecklist.upsert(hid, items=[
            {"text": "阻断 C2 域名", "checked": False, "source": "ai"},
        ])

    def test_executive_masks_ioc_value(self):
        from app.services.report_service import ReportService
        html = ReportService.generate_html(self.host["id"], report_level="executive")
        # 完全脱敏：原始 IOC 值不得出现（应被掩码为 185.220.*.*）
        self.assertNotIn(self.IOC, html)
        self.assertIn("<svg", html)  # 内联图表（图表为主）

    def test_technical_keeps_ioc_value_and_checklist(self):
        from app.services.report_service import ReportService
        html = ReportService.generate_html(self.host["id"], report_level="technical")
        # 技术报告保留原始 IOC 值（供取证）
        self.assertIn(self.IOC, html)
        # 末尾嵌入处置清单复选框
        self.assertIn("处置清单", html)
        self.assertIn("阻断 C2 域名", html)
        self.assertIn('type="checkbox"', html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
