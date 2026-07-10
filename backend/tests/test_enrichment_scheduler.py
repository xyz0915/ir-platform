#!/usr/bin/env python3
"""威胁情报外联调度脚本单元测试（T7 验收点）.

使用 FakeProvider（不联网）与构造 iocs，断言:
  - scan_pending_iocs 扫描并 enrich 全部到期/从未查询的 ioc
  - 配额耗尽时停止本轮（剩余项 skipped）
  - AUTO_ENRICHMENT=False 时 run_once 不动作
  - 单源失败隔离（单个 IOC 查询异常不阻断其余）
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))
SCRIPTS_DIR = BACKEND_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from app.config import settings  # noqa: E402

TEST_DB_PATH = str(BACKEND_DIR / "data" / "test_enrichment_scheduler.db")

from app.models.ioc import Ioc  # noqa: E402
from app.models.threat_intel import ThreatIntel, EnrichSettings  # noqa: E402
from app.services.enrichment_service import (  # noqa: E402
    EnrichmentService,
    BaseThreatIntelProvider,
    ThreatIntelQueryError,
)

import enrichment_scheduler  # noqa: E402


class FaultyProvider(BaseThreatIntelProvider):
    """第 2 次调用抛错的假 provider（验证单源失败隔离）."""

    def __init__(self, config):
        super().__init__(config)
        self.n = 0

    def query(self, ioc_type, ioc_value):
        self.n += 1
        if self.n == 2:
            raise ThreatIntelQueryError("模拟查询失败")
        return BaseThreatIntelProvider.build_normalized(
            ioc_type, ioc_value, self.name,
            {"judgments": ["malicious"], "risk_score": 90},
        )


class FakeProvider(BaseThreatIntelProvider):
    def query(self, ioc_type, ioc_value):
        return BaseThreatIntelProvider.build_normalized(
            ioc_type, ioc_value, self.name,
            {"judgments": ["malicious"], "risk_score": 90},
        )


class SchedulerTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db_path = Path(TEST_DB_PATH)
        if db_path.exists():
            db_path.unlink()
        settings.DB_PATH = TEST_DB_PATH
        from app.database import init_db

        init_db()
        EnrichmentService._instance = None

    def setUp(self):
        from app.database import get_connection

        with get_connection() as conn:
            conn.execute("DELETE FROM threat_intel")
            conn.execute("DELETE FROM iocs")
        EnrichmentService._instance = None
        self.fake = FakeProvider({"name": "fakebook", "type": "fake", "base_url": "https://fake"})
        self.patcher = mock.patch.object(
            EnrichmentService, "get_provider", return_value=self.fake
        )
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def _make_ips(self, n):
        return [
            Ioc.create(ioc_type="ip", ioc_value=f"10.10.10.{i}", source="user")
            for i in range(1, n + 1)
        ]

    def test_scan_enriches_all_pending(self):
        self._make_ips(3)
        result = EnrichmentService().scan_pending_iocs(recheck_days=30)
        self.assertEqual(result["total"], 3)
        self.assertEqual(result["enriched"], 3)
        self.assertEqual(result["skipped"], 0)

    def test_quota_stops_round(self):
        self._make_ips(4)
        svc = EnrichmentService()
        svc._daily_quota = 2
        result = svc.scan_pending_iocs(recheck_days=30)
        self.assertEqual(result["enriched"], 2)
        self.assertEqual(result["skipped"], 2)

    def test_auto_enrichment_off(self):
        """AUTO_ENRICHMENT=False 时 run_once 不执行任何动作."""
        self._make_ips(2)
        with mock.patch.object(EnrichSettings, "load", return_value={
            "auto_enrichment": False,
            "daily_quota": 1000,
            "recheck_days": 30,
            "scheduler_interval": 3600,
            "rate_limit_qps": 2,
            "enable_enrichment_feedback": True,
        }):
            result = enrichment_scheduler.run_once()
        self.assertFalse(result["auto_enrichment"])
        self.assertEqual(result["scanned"], 0)
        self.assertEqual(result["enriched"], 0)

    def test_single_source_failure_isolation(self):
        """单个 IOC 查询异常不阻断其余 IOC（单源失败隔离）."""
        self._make_ips(3)
        faulty = FaultyProvider({"name": "faulty", "type": "fake", "base_url": "https://fake"})
        with mock.patch.object(EnrichmentService, "get_provider", return_value=faulty):
            svc = EnrichmentService()
            result = svc.scan_pending_iocs(recheck_days=30)
        # 第 2 个失败，其余 2 个成功
        self.assertEqual(result["enriched"], 2)
        self.assertEqual(result["failed"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
