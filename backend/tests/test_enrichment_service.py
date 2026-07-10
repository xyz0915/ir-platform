#!/usr/bin/env python3
"""EnrichmentService 单元测试（T2/T3 验收点）.

使用 FakeProvider（不联网）验证:
  - enrich_ioc 写库 + 返回记录
  - 运行时内存去重（TTL）避免重复打 API / 重复落库
  - batch 受当日配额限制（配额耗尽本轮剩余项 skipped）
  - scan_pending_iocs 筛选（从未查询 / 超 recheck_days / 已查过的排除）
  - 非 ip/domain 上抛 UnsupportedIocTypeError
  - 单 provider 串行（查询按顺序执行，无并发交错）
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings  # noqa: E402

TEST_DB_PATH = str(BACKEND_DIR / "data" / "test_enrichment_svc.db")

from app.models.ioc import Ioc  # noqa: E402
from app.models.threat_intel import ThreatIntel  # noqa: E402
from app.services.enrichment_service import (  # noqa: E402
    EnrichmentService,
    BaseThreatIntelProvider,
    UnsupportedIocTypeError,
    QuotaExceededError,
)


class FakeProvider(BaseThreatIntelProvider):
    """不联网的假 provider，记录每次 query 调用的参数与顺序."""

    def __init__(self, config):
        super().__init__(config)
        self.calls = []
        self.judgments = config.get("judgments", ["malicious"])
        self.risk_score = config.get("risk_score", 90)

    def query(self, ioc_type, ioc_value):
        self.calls.append((ioc_type, ioc_value))
        return BaseThreatIntelProvider.build_normalized(
            ioc_type,
            ioc_value,
            self.name,
            {
                "judgments": self.judgments,
                "risk_score": self.risk_score,
                "tags": ["fake"],
            },
        )


class EnrichServiceTestCase(unittest.TestCase):
    """所有测试共享独立测试库 + FakeProvider."""

    @classmethod
    def setUpClass(cls):
        db_path = Path(TEST_DB_PATH)
        if db_path.exists():
            db_path.unlink()
        settings.DB_PATH = TEST_DB_PATH
        from app.database import init_db

        init_db()
        # 重置单例，避免跨测试污染配额
        EnrichmentService._instance = None

    def setUp(self):
        # 清空相关表
        for it in Ioc.list():
            Ioc.delete(it["id"])
        for ti in ThreatIntel.list_by_value("__all__"):
            pass
        # 直接清空 threat_intel（list_by_value 仅按值，这里用裸连接清表）
        from app.database import get_connection

        with get_connection() as conn:
            conn.execute("DELETE FROM threat_intel")
        EnrichmentService._instance = None
        self.fake = FakeProvider({
            "name": "fakebook",
            "type": "fake",
            "base_url": "https://fake",
            "rate_limit_qps": 1000,
        })
        self.patcher = mock.patch.object(
            EnrichmentService, "get_provider", return_value=self.fake
        )
        self.patcher.start()
        self.svc = EnrichmentService()

    def tearDown(self):
        self.patcher.stop()


class TestEnrichIoc(EnrichServiceTestCase):
    """enrich_ioc 写库与去重."""

    def test_enrich_ioc_persists(self):
        """enrich_ioc 应落库并返回 threat_level=high 的记录."""
        ioc = Ioc.create(ioc_type="ip", ioc_value="9.9.9.9", source="user")
        rec = self.svc.enrich_ioc(ioc["id"], "ip", "9.9.9.9")
        self.assertEqual(rec["ioc_value"], "9.9.9.9")
        self.assertEqual(rec["provider"], "fakebook")
        self.assertEqual(rec["threat_level"], "high")
        stored = ThreatIntel.list_by_ioc(ioc["id"])
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["risk_score"], 90)

    def test_dedup_avoids_double_query(self):
        """同 (value, provider) 二次 enrich 命中内存去重，不重复打 API."""
        ioc = Ioc.create(ioc_type="ip", ioc_value="8.8.8.8", source="user")
        self.svc.enrich_ioc(ioc["id"], "ip", "8.8.8.8")
        self.svc.enrich_ioc(ioc["id"], "ip", "8.8.8.8")
        # 仅第一次真正调用 provider.query
        self.assertEqual(len(self.fake.calls), 1)
        # 历史仅一条（去重不重复落库）
        stored = ThreatIntel.list_by_ioc(ioc["id"])
        self.assertEqual(len(stored), 1)

    def test_unsupported_type_raises(self):
        """url/hash/cert 等非 ip/domain 类型应上抛 UnsupportedIocTypeError."""
        with self.assertRaises(UnsupportedIocTypeError):
            self.svc.enrich_ioc(None, "url", "http://x")

    def test_scan_pending_iocs_filters(self):
        """scan_pending_iocs 仅处理从未查询 / 超 recheck 的 ioc."""
        due = Ioc.create(ioc_type="ip", ioc_value="10.0.0.1", source="user")
        already = Ioc.create(ioc_type="ip", ioc_value="10.0.0.2", source="user")
        # already 已有一个近期（now）的查询结果 → 应被排除
        ThreatIntel.create(
            ioc_id=already["id"],
            ioc_type="ip",
            ioc_value="10.0.0.2",
            provider="fakebook",
            judgments=["malicious"],
            threat_level="high",
        )
        # domain 类型也在扫描范围
        dom = Ioc.create(ioc_type="domain", ioc_value="d.example.com", source="user")

        pending = ThreatIntel.get_pending_iocs(30, "fakebook")
        pending_ids = {p["id"] for p in pending}
        self.assertIn(due["id"], pending_ids)
        self.assertIn(dom["id"], pending_ids)
        self.assertNotIn(already["id"], pending_ids)

        result = self.svc.scan_pending_iocs(recheck_days=30)
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["enriched"], 2)
        self.assertEqual(result["skipped"], 0)


class TestQuotaAndBatch(EnrichServiceTestCase):
    """batch 与配额."""

    def test_batch_respects_quota(self):
        """当日配额设为 1 时，批量 2 条仅 1 条 enriched，其余 skipped."""
        self.svc._daily_quota = 1
        items = [
            {"ioc_id": None, "ioc_type": "ip", "ioc_value": "1.1.1.1"},
            {"ioc_id": None, "ioc_type": "ip", "ioc_value": "2.2.2.2"},
        ]
        result = self.svc.enrich_batch(items)
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["enriched"], 1)
        self.assertEqual(result["skipped"], 1)
        # skipped 的原因为配额
        skipped = [d for d in result["details"] if d["status"] == "skipped"]
        self.assertTrue(any("quota" in d.get("reason", "") for d in skipped))

    def test_batch_skips_unsupported(self):
        """batch 中含 url 类型应被 skipped（不计入 enriched）."""
        items = [
            {"ioc_id": None, "ioc_type": "ip", "ioc_value": "3.3.3.3"},
            {"ioc_id": None, "ioc_type": "url", "ioc_value": "http://x"},
        ]
        result = self.svc.enrich_batch(items)
        self.assertEqual(result["enriched"], 1)
        self.assertEqual(result["skipped"], 1)

    def test_quota_exhausted_raises(self):
        """enrich_ioc 在配额耗尽时上抛 QuotaExceededError."""
        self.svc._daily_quota = 0
        with self.assertRaises(QuotaExceededError):
            self.svc.enrich_ioc(None, "ip", "4.4.4.4")


class TestSerialization(EnrichServiceTestCase):
    """单 provider 串行：查询按顺序执行."""

    def test_calls_are_sequential(self):
        items = [
            {"ioc_id": None, "ioc_type": "ip", "ioc_value": f"192.168.1.{i}"}
            for i in range(3)
        ]
        self.svc.enrich_batch(items)
        # 三次查询按 items 顺序调用（同一 provider 串行，无交错）
        self.assertEqual(
            [c[1] for c in self.fake.calls],
            ["192.168.1.0", "192.168.1.1", "192.168.1.2"],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
