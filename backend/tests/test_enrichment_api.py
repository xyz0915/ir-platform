#!/usr/bin/env python3
"""威胁情报外联相关 HTTP 接口测试（T5 验收点）.

使用 FastAPI TestClient + 管理员登录鉴权，FakeProvider 避免真实联网:
  - GET  /api/threat-intel/providers  不泄露 api_key_ref
  - PUT  /api/threat-intel/settings   更新运行策略
  - POST /api/iocs/{id}/enrich        非 ip/domain → code 400；ip → code 0 落库
  - POST /api/iocs/{id}/enrich        不存在 ioc → code 404
  - GET  /api/iocs/{id}/threat-intel  返回历史
统一返回结构 ``{code, data, message}``。
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings  # noqa: E402

TEST_DB_PATH = str(BACKEND_DIR / "data" / "test_enrichment_api.db")

from app.services.enrichment_service import (  # noqa: E402
    EnrichmentService,
    BaseThreatIntelProvider,
)


class FakeProvider(BaseThreatIntelProvider):
    """不联网的假 provider."""

    def query(self, ioc_type, ioc_value):
        return BaseThreatIntelProvider.build_normalized(
            ioc_type,
            ioc_value,
            self.name,
            {"judgments": ["malicious"], "risk_score": 90, "tags": ["fake"]},
        )


class TestEnrichmentApi(unittest.TestCase):
    """威胁情报外联接口测试."""

    @classmethod
    def setUpClass(cls):
        db_path = Path(TEST_DB_PATH)
        if db_path.exists():
            db_path.unlink()
        settings.DB_PATH = TEST_DB_PATH
        from app.database import init_db

        init_db()

        from app.main import app
        from fastapi.testclient import TestClient

        cls.app = app
        cls.client = TestClient(app)

        resp = cls.client.post(
            "/api/auth/login", json={"username": "admin", "password": "admin123"}
        )
        cls.token = resp.json()["data"]["token"]
        cls.headers = {"Authorization": f"Bearer {cls.token}"}

        cls.fake = FakeProvider({
            "name": "fakebook",
            "type": "fake",
            "base_url": "https://fake",
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
        from app.database import get_connection

        with get_connection() as conn:
            conn.execute("DELETE FROM threat_intel")
            conn.execute("DELETE FROM iocs")

    # ── providers 接口不泄露 key ──────────────────────────────
    def test_providers_no_api_key_ref(self):
        resp = self.client.get("/api/threat-intel/providers", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["code"], 0)
        for p in body["data"]:
            self.assertNotIn("api_key_ref", p)

    # ── settings 更新 ─────────────────────────────────────────
    def test_settings_roundtrip(self):
        orig = self.client.get("/api/threat-intel/settings", headers=self.headers).json()["data"]
        resp = self.client.put(
            "/api/threat-intel/settings",
            headers=self.headers,
            json={"auto_enrichment": True, "daily_quota": 500},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["code"], 0)
        self.assertTrue(resp.json()["data"]["auto_enrichment"])
        self.assertEqual(resp.json()["data"]["daily_quota"], 500)
        # 还原
        self.client.put("/api/threat-intel/settings", headers=self.headers, json=orig)

    # ── enrich 非支持类型 → 400 ───────────────────────────────
    def test_enrich_unsupported_type(self):
        create = self.client.post(
            "/api/iocs",
            headers=self.headers,
            json={"ioc_type": "url", "ioc_value": "http://evil", "enabled": True},
        )
        ioc_id = create.json()["data"]["id"]
        resp = self.client.post(f"/api/iocs/{ioc_id}/enrich", headers=self.headers, json={})
        self.assertEqual(resp.json()["code"], 400)

    # ── enrich ip 成功落库 → 200 ───────────────────────────────
    def test_enrich_ip_success(self):
        create = self.client.post(
            "/api/iocs",
            headers=self.headers,
            json={"ioc_type": "ip", "ioc_value": "7.7.7.7", "enabled": True},
        )
        ioc_id = create.json()["data"]["id"]
        resp = self.client.post(f"/api/iocs/{ioc_id}/enrich", headers=self.headers, json={})
        self.assertEqual(resp.json()["code"], 0)
        self.assertEqual(resp.json()["data"]["threat_level"], "high")
        # 历史接口
        hist = self.client.get(f"/api/iocs/{ioc_id}/threat-intel", headers=self.headers)
        self.assertEqual(hist.json()["code"], 0)
        self.assertEqual(len(hist.json()["data"]), 1)

    # ── enrich 不存在 ioc → 404 ───────────────────────────────
    def test_enrich_ioc_not_found(self):
        resp = self.client.post("/api/iocs/999999/enrich", headers=self.headers, json={})
        self.assertEqual(resp.json()["code"], 404)

    # ── batch enrich ─────────────────────────────────────────
    def test_enrich_batch(self):
        ids = []
        for v in ("1.1.1.1", "2.2.2.2"):
            c = self.client.post(
                "/api/iocs",
                headers=self.headers,
                json={"ioc_type": "ip", "ioc_value": v, "enabled": True},
            )
            ids.append(c.json()["data"]["id"])
        resp = self.client.post(
            "/api/iocs/enrich/batch", headers=self.headers, json={"ids": ids}
        )
        self.assertEqual(resp.json()["code"], 0)
        data = resp.json()["data"]
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["enriched"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
