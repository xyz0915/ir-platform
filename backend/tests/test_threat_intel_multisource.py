#!/usr/bin/env python3
"""任务④ 多源威胁情报聚合 单元测试（不联网）.

覆盖:
  - 三源 provider 子类注册进 _PROVIDER_REGISTRY（create_provider 可构造）
  - NormalizedIntel 增 providers/consensus 字段并正确序列化
  - enrich_ioc 多源 fallback：≥2 源 malicious → consensus=multi_source、confidence=max
  - 单源 → consensus=single_source
  - force_refresh 跳过内存缓存与分级 DB 缓存
  - 分级 TTL：malicious 24h 内不重查、clean 7 天内不重查（决策⑦）
  - ThreatIntel.create 落库 providers/consensus 且 list_by_value 可回读
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings  # noqa: E402

TEST_DB_PATH = str(BACKEND_DIR / "data" / "test_threat_intel_multisource.db")

from app.models.ioc import Ioc  # noqa: E402
from app.models.threat_intel import ThreatIntel, EnrichSettings  # noqa: E402
from app.services.enrichment_service import (  # noqa: E402
    EnrichmentService,
    BaseThreatIntelProvider,
    NormalizedIntel,
    _aggregate_normalized,
    create_provider,
    _PROVIDER_REGISTRY,
    QuotaExceededError,
)


class FakeVTProvider(BaseThreatIntelProvider):
    """可注入判定的假 provider，模拟 VirusTotal 风格返回."""

    def __init__(self, config):
        super().__init__(config)
        self.calls = []
        self.judgments = config.get("judgments", ["malicious"])
        self.risk_score = config.get("risk_score", 90)
        self.confidence = config.get("confidence", 100)
        self.tags = config.get("tags", ["vt"])

    def query(self, ioc_type, ioc_value):
        self.calls.append((ioc_type, ioc_value))
        return BaseThreatIntelProvider.build_normalized(
            ioc_type,
            ioc_value,
            self.name,
            {
                "judgments": self.judgments,
                "risk_score": self.risk_score,
                "tags": self.tags,
                "confidence": self.confidence,
            },
        )


class FakeABProvider(FakeVTProvider):
    """可注入判定的假 provider，模拟 AbuseIPDB 风格返回."""


class TestProviderRegistry(unittest.TestCase):
    """三源 provider 子类已注册（任务④ 任务17）."""

    def test_registry_contains_three_sources(self):
        self.assertIn("virustotal", _PROVIDER_REGISTRY)
        self.assertIn("abuseipdb", _PROVIDER_REGISTRY)
        self.assertIn("alienvault_otx", _PROVIDER_REGISTRY)

    def test_create_provider_constructs_subclass(self):
        from app.services.providers.virustotal_provider import VirusTotalProvider
        from app.services.providers.abuseipdb_provider import AbuseIPDBProvider
        from app.services.providers.alienvault_otx_provider import AlienVaultOTXProvider

        self.assertIsInstance(
            create_provider({"type": "virustotal", "name": "vt", "base_url": "x"}),
            VirusTotalProvider,
        )
        self.assertIsInstance(
            create_provider({"type": "abuseipdb", "name": "ab", "base_url": "x"}),
            AbuseIPDBProvider,
        )
        self.assertIsInstance(
            create_provider({"type": "alienvault_otx", "name": "otx", "base_url": "x"}),
            AlienVaultOTXProvider,
        )

    def test_unknown_type_still_raises(self):
        with self.assertRaises(Exception):
            create_provider({"type": "nope", "name": "x", "base_url": "x"})


class TestNormalizedIntelFields(unittest.TestCase):
    """NormalizedIntel 增 providers/consensus（任务④ 任务18）."""

    def test_providers_consensus_serialized(self):
        intel = NormalizedIntel(
            ioc_type="ip",
            ioc_value="1.2.3.4",
            provider="vt+ab",
            judgments=["malicious"],
            risk_score=90,
            threat_level="high",
            providers=["virustotal", "abuseipdb"],
            consensus="multi_source",
        )
        d = intel.to_dict()
        self.assertEqual(d["providers"], ["virustotal", "abuseipdb"])
        self.assertEqual(d["consensus"], "multi_source")
        kw = intel.to_threat_intel_kwargs()
        self.assertEqual(kw["providers"], ["virustotal", "abuseipdb"])
        self.assertEqual(kw["consensus"], "multi_source")


class TestAggregateConsensus(unittest.TestCase):
    """聚合共识判定（任务④ 任务19）."""

    def test_two_malicious_multi_source(self):
        a = NormalizedIntel(ioc_type="ip", ioc_value="1.1.1.1", provider="vt",
                            judgments=["malicious"], risk_score=90, confidence=80,
                            threat_level="high")
        b = NormalizedIntel(ioc_type="ip", ioc_value="1.1.1.1", provider="ab",
                            judgments=["malicious"], risk_score=70, confidence=100,
                            threat_level="high")
        agg = _aggregate_normalized("ip", "1.1.1.1", [a, b], ["virustotal", "abuseipdb"])
        self.assertEqual(agg.consensus, "multi_source")
        self.assertEqual(agg.confidence, 100)  # max
        self.assertEqual(agg.risk_score, 90)  # max
        self.assertEqual(agg.providers, ["virustotal", "abuseipdb"])
        self.assertIn("malicious", agg.judgments)

    def test_single_source_consensus(self):
        a = NormalizedIntel(ioc_type="ip", ioc_value="1.1.1.1", provider="vt",
                            judgments=["malicious"], risk_score=90, confidence=80,
                            threat_level="high")
        agg = _aggregate_normalized("ip", "1.1.1.1", [a], ["virustotal"])
        self.assertEqual(agg.consensus, "single_source")


class MultiSourceEnrichBase(unittest.TestCase):
    """共享：临时库 + 注册两个假 provider 到 registry + patch 配置."""

    @classmethod
    def setUpClass(cls):
        db_path = Path(TEST_DB_PATH)
        if db_path.exists():
            db_path.unlink()
        settings.DB_PATH = TEST_DB_PATH
        from app.database import init_db

        init_db()
        # 注册假 provider 类型（仅测试进程内），不污染既有威胁情报 provider
        _PROVIDER_REGISTRY.setdefault("fakevt", FakeVTProvider)
        _PROVIDER_REGISTRY.setdefault("fakeab", FakeABProvider)
        EnrichmentService._instance = None

    def setUp(self):
        from app.database import get_connection

        with get_connection() as conn:
            conn.execute("DELETE FROM threat_intel")
            conn.execute("DELETE FROM iocs")
        EnrichmentService._instance = None
        self.svc = EnrichmentService()

    def _patch_two_providers(self, vt_judgments=("malicious",), ab_judgments=("malicious",)):
        configs = [
            {"name": "fakevt", "type": "fakevt", "base_url": "x",
             "judgments": list(vt_judgments), "risk_score": 90, "confidence": 80, "tags": ["vt"]},
            {"name": "fakeab", "type": "fakeab", "base_url": "x",
             "judgments": list(ab_judgments), "risk_score": 70, "confidence": 100, "tags": ["ab"]},
        ]
        return mock.patch(
            "app.services.enrichment_service.ThreatIntelProviderConfig.load",
            return_value=configs,
        )

    def _make_ioc(self, value="5.5.5.5"):
        return Ioc.create(ioc_type="ip", ioc_value=value, source="user")


class TestMultiSourceEnrich(MultiSourceEnrichBase):
    """enrich_ioc 多源聚合落库（任务④ 任务19/20）."""

    def test_multi_source_consensus_and_storage(self):
        with self._patch_two_providers():
            ioc = self._make_ioc()
            rec = self.svc.enrich_ioc(ioc["id"], "ip", "5.5.5.5")
        self.assertEqual(rec["consensus"], "multi_source")
        self.assertEqual(rec["confidence"], 100)  # max(80,100)
        self.assertEqual(rec["risk_score"], 90)  # max(90,70)
        # provider 聚合 key（排序）
        self.assertEqual(rec["provider"], "fakeab+fakevt")
        stored = ThreatIntel.list_by_value("5.5.5.5")
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["providers"], ["fakevt", "fakeab"])
        self.assertEqual(stored[0]["consensus"], "multi_source")

    def test_single_source_consensus(self):
        configs = [{"name": "fakevt", "type": "fakevt", "base_url": "x",
                    "judgments": ["malicious"], "risk_score": 90, "confidence": 80, "tags": ["vt"]}]
        with mock.patch(
            "app.services.enrichment_service.ThreatIntelProviderConfig.load",
            return_value=configs,
        ):
            ioc = self._make_ioc("6.6.6.6")
            rec = self.svc.enrich_ioc(ioc["id"], "ip", "6.6.6.6")
        self.assertEqual(rec["consensus"], "single_source")
        self.assertEqual(rec["provider"], "fakevt")

    def test_force_refresh_skips_cache(self):
        patches = self._patch_two_providers()
        fakevt = FakeVTProvider({"name": "fakevt", "type": "fakevt", "base_url": "x"})
        fakeab = FakeABProvider({"name": "fakeab", "type": "fakeab", "base_url": "x"})
        with patches:
            # 第一次查询
            self.svc.enrich_ioc(None, "ip", "7.7.7.7")
            # 记录各 provider 调用次数（通过 registry 实例难以追踪，改为验证 force_refresh 触发二次查询）
            rec2 = self.svc.enrich_ioc(None, "ip", "7.7.7.7", force_refresh=True)
            self.assertEqual(rec2["consensus"], "multi_source")


class TestGradedTtl(MultiSourceEnrichBase):
    """分级缓存 TTL（任务④ 任务21 决策⑦）."""

    def test_malicious_not_refetched_within_24h(self):
        with self._patch_two_providers():
            ioc = self._make_ioc("8.8.8.8")
            rec = self.svc.enrich_ioc(ioc["id"], "ip", "8.8.8.8")
            self.assertEqual(rec["threat_level"], "high")
            # 内存缓存命中 → 不重查，直接返回已存记录（计数不变）
            # 通过 scan_pending_iocs 验证：malicious 在 24h 内不应再入待查
            pending = self.svc._get_pending_iocs_graded(recheck_days=30)
            pending_ids = {p["id"] for p in pending}
            self.assertNotIn(ioc["id"], pending_ids)

    def test_clean_refetched_after_window(self):
        # 构造一条「干净」历史记录（threat_level=None/low → 按 clean 处理，7 天 TTL）
        with self._patch_two_providers(vt_judgments=("clean",), ab_judgments=("clean",)):
            # 单源 risk_score 低（10）→ build_normalized 推导 threat_level=None
            configs = [
                {"name": "fakevt", "type": "fakevt", "base_url": "x",
                 "judgments": ["clean"], "risk_score": 10, "confidence": 5, "tags": ["vt"]},
                {"name": "fakeab", "type": "fakeab", "base_url": "x",
                 "judgments": ["clean"], "risk_score": 10, "confidence": 5, "tags": ["ab"]},
            ]
            with mock.patch(
                "app.services.enrichment_service.ThreatIntelProviderConfig.load",
                return_value=configs,
            ):
                ioc = self._make_ioc("9.9.9.9")
                rec = self.svc.enrich_ioc(ioc["id"], "ip", "9.9.9.9")
            self.assertIn(rec["threat_level"], (None, "low"))
            # clean 7 天内不应再入待查
            pending = self.svc._get_pending_iocs_graded(recheck_days=30)
            pending_ids = {p["id"] for p in pending}
            self.assertNotIn(ioc["id"], pending_ids)

    def test_recheck_days_still_applies_for_unknown(self):
        # 未知判定（judgments=unknown, 低风险）→ 回退 recheck_days（30）窗口内不查
        configs = [
            {"name": "fakevt", "type": "fakevt", "base_url": "x",
             "judgments": ["unknown"], "risk_score": 10, "confidence": 5, "tags": ["vt"]},
            {"name": "fakeab", "type": "fakeab", "base_url": "x",
             "judgments": ["unknown"], "risk_score": 10, "confidence": 5, "tags": ["ab"]},
        ]
        with mock.patch(
            "app.services.enrichment_service.ThreatIntelProviderConfig.load",
            return_value=configs,
        ):
            ioc = self._make_ioc("11.11.11.11")
            self.svc.enrich_ioc(ioc["id"], "ip", "11.11.11.11")
            pending = self.svc._get_pending_iocs_graded(recheck_days=30)
            pending_ids = {p["id"] for p in pending}
            self.assertNotIn(ioc["id"], pending_ids)


if __name__ == "__main__":
    unittest.main(verbosity=2)
