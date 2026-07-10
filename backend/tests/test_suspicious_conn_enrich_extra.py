#!/usr/bin/env python3
"""独立补强断言：可疑外连「一键威胁情报检测」（在既有 7 用例之外追加）.

本文件不改动工程师既有 test_suspicious_conn_enrich.py，仅补充更细的强约束断言：

- 私网地址被跳过（skipped_private 计数正确，结果 threat_level 未写回；覆盖
  private/loopback/link-local/multicast/unspecified 各类）
- 重复 IP 只 enrich 一次（provider 调用次数 == 去重后公网数，且调用集合正确）
- high → 行 threat_level="high"、threat_tags 可解析含语义标记
- medium → "medium"
- low/clean → "low" 且标签语义干净（真实 provider 对 clean 返回 low）
- threat_intel 表对该 IP 有留痕且 ioc_id 为 NULL
- IPv6 公网 enrichment、私网/链路本地/loopback 跳过
- API 路由对不存在 host_id 返回 404

注意：build_normalized 的 _level_from_judgments 仅能产出 high/medium/None，
无法产出 "low"（clean 会落到 None）。但真实 ThreatBookProvider 对 clean/low
会显式返回 threat_level="low"。为忠实模拟真实 provider 行为并验证
low/clean → "low" 的写回路径，本文件的 FakeProvider 允许按 IP 显式指定
threat_level，clean 场景显式返回 "low"（与真实 provider 一致）。
"""

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings  # noqa: E402

TEST_DB_PATH = str(BACKEND_DIR / "data" / "test_suspicious_conn_enrich_extra.db")

from app.database import get_connection, init_db  # noqa: E402
from app.models.analysis import SuspiciousConnection  # noqa: E402
from app.models.threat_intel import ThreatIntel  # noqa: E402
from app.services.analysis_service import AnalysisService  # noqa: E402
from app.services.enrichment_service import (  # noqa: E402
    EnrichmentService,
    BaseThreatIntelProvider,
    NormalizedIntel,
)


class ConfigurableFakeProvider(BaseThreatIntelProvider):
    """可配置返回判定等级的假 provider（不联网）.

    - per_ip: 按 IP 指定 {"judgments", "risk_score", "tags", "threat_level"}。
    - 若指定了 threat_level 则直接构造 NormalizedIntel（忠实模拟真实 provider
      对 clean/low 返回 "low" 的行为）；否则走 build_normalized 推导。
    """

    def __init__(self, config):
        super().__init__(config)
        self.calls = []
        self.per_ip = config.get("per_ip", {})
        self.default_judgments = config.get("judgments", ["malicious"])
        self.default_risk_score = config.get("risk_score", 90)
        self.default_tags = config.get("tags", ["fake"])

    def query(self, ioc_type, ioc_value):
        self.calls.append((ioc_type, ioc_value))
        spec = self.per_ip.get(ioc_value, {})
        judgments = spec.get("judgments", self.default_judgments)
        risk_score = spec.get("risk_score", self.default_risk_score)
        tags = spec.get("tags", self.default_tags)
        threat_level = spec.get("threat_level")
        if threat_level is None:
            return BaseThreatIntelProvider.build_normalized(
                ioc_type,
                ioc_value,
                self.name,
                {"judgments": judgments, "risk_score": risk_score, "tags": tags},
            )
        # 忠实模拟真实 provider：clean/low → "low"
        return NormalizedIntel(
            ioc_type=ioc_type,
            ioc_value=ioc_value,
            provider=self.name,
            risk_score=int(risk_score or 0),
            judgments=list(judgments or []),
            tags=list(tags or []),
            threat_level=threat_level,
            raw_summary=f"mock threat_level={threat_level}",
        )


def make_host() -> int:
    """插入一个 case + host，返回 host_id（满足外键约束）."""
    with get_connection() as conn:
        conn.execute("INSERT INTO cases (name) VALUES ('qa-extra')")
        cid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO hosts (case_id, hostname, status) VALUES (?, 'host-qa-extra', 'analyzed')",
            (cid,),
        )
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


PER_IP_SPEC = {
    "1.2.3.4": {"judgments": ["malicious"], "risk_score": 95, "tags": ["c2", "malware"]},
    "5.6.7.8": {"judgments": ["suspicious"], "risk_score": 70, "tags": ["proxy"]},
    "9.10.11.12": {"judgments": ["clean"], "risk_score": 10, "tags": ["cdn"], "threat_level": "low"},
}


class BaseExtra(unittest.TestCase):
    """共享独立测试库 + 清空相关表."""

    @classmethod
    def setUpClass(cls):
        db_path = Path(TEST_DB_PATH)
        if db_path.exists():
            db_path.unlink()
        settings.DB_PATH = TEST_DB_PATH
        init_db()  # 含 _alter_suspicious_connections_table 迁移
        cls.patcher = mock.patch.object(
            EnrichmentService,
            "get_provider",
            return_value=ConfigurableFakeProvider({
                "name": "fakebook",
                "type": "fake",
                "base_url": "https://fake",
                "rate_limit_qps": 1000,
                "per_ip": PER_IP_SPEC,
            }),
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
        self.host_id = make_host()
        provider = EnrichmentService.get_provider()
        if provider is not None:
            provider.calls = []

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


class TestExtraCoverage(BaseExtra):
    """核心强约束断言：过滤 / 去重 / 三级写回 / 留痕."""

    def test_private_all_categories_skipped_not_written(self):
        """私网/loopback/link-local/multicast/unspecified 全部跳过且未写回。"""
        self._seed([
            "192.168.1.50",   # private (RFC1918)
            "10.0.0.5",       # private (RFC1918)
            "172.16.5.5",     # private (RFC1918 16-31)
            "127.0.0.1",      # loopback
            "169.254.1.1",    # link-local
            "224.0.0.1",      # multicast
            "0.0.0.0",        # unspecified
            "1.2.3.4",        # public high
        ])
        stats = AnalysisService.enrich_suspicious_connections(self.host_id)
        self.assertEqual(stats["total"], 8)
        self.assertEqual(stats["public"], 1)
        self.assertEqual(stats["skipped_private"], 7)
        self.assertEqual(stats["enriched"], 1)
        self.assertEqual(stats["malicious"], 1)
        rows = SuspiciousConnection.list_by_host(self.host_id)
        for row in rows:
            if row["remote_address"] == "1.2.3.4":
                self.assertEqual(row["threat_level"], "high")
                self.assertIsNotNone(row["enriched_at"])
            else:
                # 非公网地址一律不应写回威胁情报
                self.assertIsNone(
                    row["threat_level"],
                    f"{row['remote_address']} 为私网/保留地址，不应写回 threat_level",
                )

    def test_duplicate_ip_enriched_once(self):
        """重复 IP 只 enrich 一次（provider 调用次数 == 去重后公网数）。"""
        self._seed(["1.2.3.4", "1.2.3.4", "1.2.3.4", "5.6.7.8", "9.10.11.12"])
        provider = EnrichmentService.get_provider()
        provider.calls = []
        stats = AnalysisService.enrich_suspicious_connections(self.host_id)
        self.assertEqual(stats["public"], 3)
        # 3 个不同公网 IP，各调用 provider 一次（无重复打 API）
        self.assertEqual(len(provider.calls), 3)
        called_ips = {c[1] for c in provider.calls}
        self.assertEqual(called_ips, {"1.2.3.4", "5.6.7.8", "9.10.11.12"})

    def test_high_medium_low_levels_and_tags(self):
        """high/medium/low 三级分别正确写回，threat_tags 可解析含语义标记。"""
        self._seed(["1.2.3.4", "5.6.7.8", "9.10.11.12"])
        stats = AnalysisService.enrich_suspicious_connections(self.host_id)
        self.assertEqual(stats["malicious"], 1)
        self.assertEqual(stats["suspicious"], 1)
        rows = {r["remote_address"]: r for r in SuspiciousConnection.list_by_host(self.host_id)}
        # high
        self.assertEqual(rows["1.2.3.4"]["threat_level"], "high")
        self.assertEqual(rows["1.2.3.4"]["threat_score"], 95)
        tags_high = json.loads(rows["1.2.3.4"]["threat_tags"])
        self.assertIn("c2", tags_high)
        self.assertIn("malware", tags_high)
        # medium
        self.assertEqual(rows["5.6.7.8"]["threat_level"], "medium")
        self.assertEqual(json.loads(rows["5.6.7.8"]["threat_tags"]), ["proxy"])
        # low / clean
        self.assertEqual(rows["9.10.11.12"]["threat_level"], "low")
        self.assertEqual(json.loads(rows["9.10.11.12"]["threat_tags"]), ["cdn"])

    def test_threat_intel_kept_with_null_ioc_id(self):
        """threat_intel 表对该 IP 有留痕且 ioc_id 为 NULL（不强制转 IOC）。"""
        self._seed(["1.2.3.4"])
        AnalysisService.enrich_suspicious_connections(self.host_id)
        records = ThreatIntel.list_by_value("1.2.3.4")
        self.assertEqual(len(records), 1)
        self.assertIsNone(records[0]["ioc_id"])
        self.assertEqual(records[0]["provider"], "fakebook")
        self.assertEqual(records[0]["threat_level"], "high")
        self.assertEqual(records[0]["ioc_type"], "ip")


class TestExtraIpv6(BaseExtra):
    """IPv6 公网 enrichment 与私网/链路本地/loopback 跳过。"""

    def test_ipv6_classification(self):
        self._seed([
            "2606:4700:4700::1111",  # public IPv6 (Cloudflare DNS)
            "fe80::1",                # link-local → skip
            "fc00::1",                # unique local (private) → skip
            "::1",                    # loopback → skip
            "192.168.0.1",            # IPv4 private → skip
        ])
        stats = AnalysisService.enrich_suspicious_connections(self.host_id)
        self.assertEqual(stats["total"], 5)
        self.assertEqual(stats["public"], 1)
        self.assertEqual(stats["skipped_private"], 4)
        self.assertEqual(stats["enriched"], 1)
        rows = {r["remote_address"]: r for r in SuspiciousConnection.list_by_host(self.host_id)}
        self.assertEqual(rows["2606:4700:4700::1111"]["threat_level"], "high")
        self.assertIsNone(rows["fe80::1"]["threat_level"])
        self.assertIsNone(rows["fc00::1"]["threat_level"])
        self.assertIsNone(rows["::1"]["threat_level"])
        self.assertIsNone(rows["192.168.0.1"]["threat_level"])


class TestExtraApi(BaseExtra):
    """API 路由验收：不存在 host_id 返回 404。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from app.main import app
        from fastapi.testclient import TestClient

        cls.client = TestClient(app)
        resp = cls.client.post(
            "/api/auth/login", json={"username": "admin", "password": "admin123"}
        )
        cls.token = resp.json()["data"]["token"]
        cls.headers = {"Authorization": f"Bearer {cls.token}"}

    def test_api_404_for_missing_host(self):
        resp = self.client.post(
            "/api/hosts/999999/suspicious-connections/enrich", headers=self.headers
        )
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
