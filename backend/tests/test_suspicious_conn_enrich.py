#!/usr/bin/env python3
"""可疑外连「一键威胁情报检测」单元测试（增量功能验收）.

复用 EnrichmentService 的 FakeProvider（不联网）验证:
  - public IP 提取（ipaddress 校验）
  - 私网/保留地址过滤（private/loopback/link-local/multicast/reserved/unspecified）
  - 按 remote_address 去重
  - 检测结果（threat_level/risk_score/threat_tags）正确写回 suspicious_connections
  - threat_intel 表留痕（ioc_id 为 NULL）
  - enrich_suspicious_connections 返回统计 {total, public, enriched, malicious, suspicious, skipped_private, errors}
  - 无 provider 配置时不崩溃（单条失败不影响整体）
  - API 路由 POST /api/hosts/{host_id}/suspicious-connections/enrich 返回统计
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings  # noqa: E402

TEST_DB_PATH = str(BACKEND_DIR / "data" / "test_suspicious_conn_enrich.db")

from app.database import get_connection, init_db  # noqa: E402
from app.models.analysis import SuspiciousConnection  # noqa: E402
from app.models.threat_intel import ThreatIntel  # noqa: E402
from app.services.analysis_service import AnalysisService  # noqa: E402
from app.services.enrichment_service import (  # noqa: E402
    EnrichmentService,
    BaseThreatIntelProvider,
)


class FakeProvider(BaseThreatIntelProvider):
    """不联网的假 provider，可控制返回的 threat_level."""

    def __init__(self, config):
        super().__init__(config)
        self.calls = []
        self.judgments = config.get("judgments", ["malicious"])
        self.risk_score = config.get("risk_score", 90)
        self.tags = config.get("tags", ["fake"])

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
            },
        )


def make_host() -> int:
    """插入一个 case + host，返回 host_id（满足外键约束）."""
    with get_connection() as conn:
        conn.execute("INSERT INTO cases (name) VALUES ('qa-case')")
        cid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO hosts (case_id, hostname, status) VALUES (?, 'host-qa', 'analyzed')",
            (cid,),
        )
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


class BaseSuspiciousConnEnrich(unittest.TestCase):
    """共享独立测试库 + 清空相关表."""

    @classmethod
    def setUpClass(cls):
        db_path = Path(TEST_DB_PATH)
        if db_path.exists():
            db_path.unlink()
        settings.DB_PATH = TEST_DB_PATH
        # init_db 会执行 _alter_suspicious_connections_table，确保新列存在
        init_db()
        cls.fake = FakeProvider({
            "name": "fakebook",
            "type": "fake",
            "base_url": "https://fake",
            "rate_limit_qps": 1000,
        })
        cls.patcher = mock.patch.object(
            EnrichmentService, "get_provider", return_value=cls.fake
        )
        cls.patcher.start()
        EnrichmentService._instance = None

    @classmethod
    def tearDownClass(cls):
        cls.patcher.stop()

    def setUp(self):
        with get_connection() as conn:
            conn.execute("DELETE FROM suspicious_connections")
            conn.execute("DELETE FROM threat_intel")
            conn.execute("DELETE FROM hosts")
            conn.execute("DELETE FROM cases")
        EnrichmentService._instance = None
        # 重置共享 fake 的状态（避免被其它用例 mutate 后污染）
        self.fake.calls = []
        self.fake.judgments = ["malicious"]
        self.fake.risk_score = 90
        self.fake.tags = ["fake"]
        self.host_id = make_host()

    def _seed(self, rows):
        """批量插入可疑外连行。rows 为 remote_address 列表或含完整字段的 dict 列表。"""
        items = []
        for r in rows:
            if isinstance(r, str):
                items.append({
                    "protocol": "tcp",
                    "local_address": "0.0.0.0",
                    "local_port": 0,
                    "remote_address": r,
                    "remote_port": 443,
                    "state": "ESTABLISHED",
                    "process_name": "svchost.exe",
                    "pid": 1234,
                    "reason": "可疑外连",
                    "rule_name": "r1",
                    "severity": "medium",
                })
            else:
                items.append(r)
        return SuspiciousConnection.batch_create(self.host_id, items)


class TestPublicIpExtraction(BaseSuspiciousConnEnrich):
    """公网 IP 提取、私网过滤、去重与写回."""

    def test_public_private_dedup(self):
        """1 个公网 IP（重复 2 行）+ 2 个私网 → 统计正确且写回。"""
        self._seed([
            "8.8.8.8",
            "8.8.8.8",  # 去重
            "192.168.1.50",  # RFC1918 私网
            "10.0.0.1",  # RFC1918 私网
        ])
        stats = AnalysisService.enrich_suspicious_connections(self.host_id)
        self.assertEqual(stats["total"], 4)
        self.assertEqual(stats["public"], 1)
        self.assertEqual(stats["enriched"], 1)
        self.assertEqual(stats["malicious"], 1)
        self.assertEqual(stats["suspicious"], 0)
        self.assertEqual(stats["skipped_private"], 2)
        self.assertEqual(len(stats["errors"]), 0)

        # 写回校验：8.8.8.8 的两条行均应为 high
        rows = SuspiciousConnection.list_by_host(self.host_id)
        for row in rows:
            if row["remote_address"] == "8.8.8.8":
                self.assertEqual(row["threat_level"], "high")
                self.assertEqual(row["threat_score"], 90)
                self.assertIsNotNone(row["enriched_at"])
                self.assertIsNotNone(row["threat_tags"])
            else:
                # 私网地址不应被写回
                self.assertIsNone(row["threat_level"])

    def test_suspicious_level_count(self):
        """FakeProvider 返回 suspicious → 计入 suspicious。"""
        self.fake.judgments = ["suspicious"]
        self.fake.risk_score = 70
        self._seed(["1.1.1.1", "1.1.1.1", "172.16.0.9"])
        stats = AnalysisService.enrich_suspicious_connections(self.host_id)
        self.assertEqual(stats["public"], 1)
        self.assertEqual(stats["suspicious"], 1)
        self.assertEqual(stats["malicious"], 0)
        self.assertEqual(stats["skipped_private"], 1)

    def test_threat_tags_stored_as_json(self):
        """threat_tags 应以 JSON 字符串落库并可解析。"""
        self.fake.tags = ["c2", "malware"]
        self._seed(["9.9.9.9"])
        AnalysisService.enrich_suspicious_connections(self.host_id)
        rows = SuspiciousConnection.list_by_host(self.host_id)
        row = next(r for r in rows if r["remote_address"] == "9.9.9.9")
        self.assertEqual(row["threat_level"], "high")
        # threat_tags 为 JSON 字符串，解析后应包含标签
        import json
        tags = json.loads(row["threat_tags"])
        self.assertIn("c2", tags)

    def test_threat_intel_keep_history(self):
        """threat_intel 表应留痕（ioc_id 为 NULL）。"""
        self._seed(["9.9.9.11"])
        AnalysisService.enrich_suspicious_connections(self.host_id)
        records = ThreatIntel.list_by_value("9.9.9.11")
        self.assertEqual(len(records), 1)
        self.assertIsNone(records[0]["ioc_id"])
        self.assertEqual(records[0]["provider"], "fakebook")


class TestNoProviderNoCrash(BaseSuspiciousConnEnrich):
    """无 provider 配置时不崩溃（单条失败不影响整体）。"""

    @mock.patch.object(EnrichmentService, "get_provider", return_value=None)
    def test_no_provider_returns_errors(self, _patched):
        EnrichmentService._instance = None
        self._seed(["8.8.8.8", "192.168.1.1"])
        # 不应抛异常
        stats = AnalysisService.enrich_suspicious_connections(self.host_id)
        self.assertEqual(stats["public"], 1)
        self.assertEqual(stats["skipped_private"], 1)
        self.assertEqual(stats["enriched"], 0)
        # 公网 IP 因无 provider 失败，记录到 errors
        self.assertEqual(len(stats["errors"]), 1)
        self.assertEqual(stats["errors"][0]["ip"], "8.8.8.8")
        # 未写回任何威胁情报
        rows = SuspiciousConnection.list_by_host(self.host_id)
        for r in rows:
            self.assertIsNone(r["threat_level"])


class TestEnrichSuspiciousConnApi(BaseSuspiciousConnEnrich):
    """HTTP 接口验收：POST /api/hosts/{host_id}/suspicious-connections/enrich。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from app.main import app
        from fastapi.testclient import TestClient

        cls.app = app
        cls.client = TestClient(app)
        resp = cls.client.post(
            "/api/auth/login", json={"username": "admin", "password": "admin123"}
        )
        cls.token = resp.json()["data"]["token"]
        cls.headers = {"Authorization": f"Bearer {cls.token}"}

    def test_api_enrich_returns_stats(self):
        hid = make_host()
        items = [dict(
            protocol="tcp", local_address="0.0.0.0", local_port=0,
            remote_address="8.8.8.8", remote_port=443, state="ESTABLISHED",
            process_name="x", pid=1, reason="r", rule_name="r1", severity="medium",
        ) for _ in range(2)]
        SuspiciousConnection.batch_create(hid, items)
        resp = self.client.post(
            f"/api/hosts/{hid}/suspicious-connections/enrich", headers=self.headers
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["code"], 0)
        data = body["data"]
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["public"], 1)
        self.assertEqual(data["enriched"], 1)
        self.assertEqual(data["malicious"], 1)

    def test_api_host_not_found(self):
        resp = self.client.post(
            "/api/hosts/999999/suspicious-connections/enrich", headers=self.headers
        )
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
