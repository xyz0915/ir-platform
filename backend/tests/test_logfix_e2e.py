"""端到端冒烟测试：ACL + DSL + 导出脱敏审计 + NL 预览 + 时间（开发自测）。

覆盖：
- P0-2 ACL：admin 全量 / analyst 授权过滤 / 越权 403 / 授权管理 API
- P0-1 DSL：/search/advanced、/search?dsl=、注入拒绝
- P0-4 导出：masked 脱敏、export_audit_log 落库、export-audits admin only
- P0-3 NL：preview_only 不查库 + query_plan + nl_text>200 → 400
- P1-1 时间：parse_client_time 兼容 T/Z/毫秒

使用临时隔离 SQLite + FastAPI TestClient。
"""

import asyncio
import json
import os
import tempfile
import unittest

import app.config as config
from app.database import init_db, get_connection
from app.models.user import User
from app.services.auth_service import create_token, hash_password


def _make_isolated_db(seed_acl: bool = False):
    fd, path = tempfile.mkstemp(suffix=".db", prefix="qa_e2e_")
    os.close(fd)
    config.settings.DB_PATH = path
    config.settings.DB_JOURNAL_MODE = "DELETE"
    if seed_acl:
        os.environ["IR_ACL_INITIAL_GRANT_ALL"] = "true"
    try:
        init_db()
    finally:
        os.environ.pop("IR_ACL_INITIAL_GRANT_ALL", None)
    return path


def _cleanup_db(path):
    import gc

    gc.collect()
    for suffix in ("", "-wal", "-shm"):
        p = path + suffix
        if os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass


def _seed_data():
    """写入 cases → hosts → security_events（含 evidence JSON）。"""
    with get_connection() as conn:
        conn.execute("INSERT INTO cases (name, case_number) VALUES (?, ?)", ("caseA", "C-A"))
        conn.execute("INSERT INTO cases (name, case_number) VALUES (?, ?)", ("caseB", "C-B"))
        ca = conn.execute("SELECT id FROM cases WHERE name='caseA'").fetchone()["id"]
        cb = conn.execute("SELECT id FROM cases WHERE name='caseB'").fetchone()["id"]
        conn.execute("INSERT INTO hosts (case_id, hostname) VALUES (?, ?)", (ca, "hostA1"))
        conn.execute("INSERT INTO hosts (case_id, hostname) VALUES (?, ?)", (ca, "hostA2"))
        conn.execute("INSERT INTO hosts (case_id, hostname) VALUES (?, ?)", (cb, "hostB1"))
        ha1 = conn.execute("SELECT id FROM hosts WHERE hostname='hostA1'").fetchone()["id"]
        ha2 = conn.execute("SELECT id FROM hosts WHERE hostname='hostA2'").fetchone()["id"]
        hb1 = conn.execute("SELECT id FROM hosts WHERE hostname='hostB1'").fetchone()["id"]
        # 三条事件：A1 high / A2 high / B1 low
        rows = [
            ("e1", "2026-07-14 09:00:00", ha1, "process_start", "high", "pending", '{"source_ip": "1.1.1.1", "user_name": "admin"}'),
            ("e2", "2026-07-14 09:05:00", ha2, "network_outbound", "high", "pending", '{"source_ip": "1.1.1.2", "target_ip": "8.8.8.8"}'),
            ("e3", "2026-07-14 09:10:00", hb1, "process_start", "low", "resolved", '{"source_ip": "2.2.2.2"}'),
        ]
        for eid, ts, hid, etype, sev, status, evidence in rows:
            conn.execute(
                "INSERT INTO security_events (id, timestamp, host_id, event_type, severity, status, event_key, evidence) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (eid, ts, hid, etype, sev, status, "k_" + eid, evidence),
            )
        conn.commit()
        return ca, cb, ha1, ha2, hb1


class TestLogFixE2E(unittest.TestCase):
    """共享隔离库 + TestClient（每个测试方法重置 ACL 授权状态，避免污染）。"""

    @classmethod
    def setUpClass(cls):
        cls._db_path = _make_isolated_db()
        cls.ca, cls.cb, cls.ha1, cls.ha2, cls.hb1 = _seed_data()
        cls.admin = User.get_by_username("admin")
        cls.analyst = User.create("analyst", hash_password("x"), "analyst")
        cls.admin_token = create_token({"id": cls.admin["id"], "username": "admin", "role": "admin"})
        cls.analyst_token = create_token({"id": cls.analyst["id"], "username": "analyst", "role": "analyst"})

        from fastapi.testclient import TestClient
        import app.main as main_mod

        cls.client = TestClient(main_mod.app)

    @classmethod
    def tearDownClass(cls):
        _cleanup_db(cls._db_path)
        cls._db_path = None

    def setUp(self):
        """每个测试重置 analyst 授权：仅 caseA viewer。"""
        with get_connection() as conn:
            conn.execute("DELETE FROM user_case_access WHERE user_id = ?", (self.analyst["id"],))
            conn.execute("DELETE FROM export_audit_log")
            conn.commit()
        from app.services.access_control import grant_case_access

        grant_case_access(self.admin, self.analyst["id"], self.ca, "viewer")

    def _h(self, token):
        return {"Authorization": f"Bearer {token}"}

    # ── P0-2 ACL ──────────────────────────────────────────────
    def test_admin_sees_all_cases(self):
        r = self.client.get("/api/cases/with-hosts", headers=self._h(self.admin_token))
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) == 2  # caseA + caseB

    def test_analyst_sees_only_granted_case(self):
        r = self.client.get("/api/cases/with-hosts", headers=self._h(self.analyst_token))
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) == 1
        assert data[0]["name"] == "caseA"
        assert len(data[0]["children"]) == 2  # hostA1 + hostA2

    def test_search_analyst_injected_hosts(self):
        r = self.client.get("/api/log-search/search", headers=self._h(self.analyst_token))
        assert r.status_code == 200
        data = r.json()["data"]
        host_ids = {it["host_id"] for it in data["items"]}
        assert host_ids == {self.ha1, self.ha2}

    def test_search_analyst_forbidden_host_403(self):
        r = self.client.get(
            f"/api/log-search/search?host_id={self.hb1}", headers=self._h(self.analyst_token)
        )
        assert r.status_code == 403

    def test_admin_grant_api_and_403_for_non_admin(self):
        # 非 admin 调用授权 API → 403
        r = self.client.get(f"/api/users/{self.analyst['id']}/access", headers=self._h(self.analyst_token))
        assert r.status_code == 403
        # admin list
        r = self.client.get(f"/api/users/{self.analyst['id']}/access", headers=self._h(self.admin_token))
        assert r.status_code == 200
        assert len(r.json()["data"]["items"]) == 1
        # admin grant → analyst now sees caseB
        r = self.client.post(
            f"/api/users/{self.analyst['id']}/access",
            json={"case_id": self.cb, "role_in_case": "viewer"},
            headers=self._h(self.admin_token),
        )
        assert r.status_code == 200
        r = self.client.get("/api/cases/with-hosts", headers=self._h(self.analyst_token))
        assert len(r.json()["data"]) == 2

    def test_analyst_import_requires_analyst_role(self):
        # viewer 角色不允许 POST /import（写操作 min_role=analyst）
        r = self.client.post(
            "/api/log-search/import",
            json={"host_id": self.ha1, "collector_type": "custom", "raw_json": "{}"},
            headers=self._h(self.analyst_token),
        )
        assert r.status_code == 403

    # ── P0-1 DSL ──────────────────────────────────────────────
    def test_dsl_search_advanced(self):
        r = self.client.get(
            "/api/log-search/search/advanced",
            params={"dsl": 'severity=="high"'},
            headers=self._h(self.analyst_token),
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["total"] == 2
        assert data["dsl"]["parsed"]

    def test_dsl_search_with_or(self):
        r = self.client.get(
            "/api/log-search/search",
            params={"dsl": 'severity=="high" or severity=="critical"'},
            headers=self._h(self.analyst_token),
        )
        assert r.status_code == 200
        assert r.json()["data"]["total"] == 2

    def test_dsl_search_evidence_json(self):
        r = self.client.get(
            "/api/log-search/search",
            params={"dsl": 'source_ip~"1.1.1.1"'},
            headers=self._h(self.analyst_token),
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["total"] == 1
        assert data["items"][0]["id"] == "e1"

    def test_dsl_injection_rejected_400(self):
        r = self.client.get(
            "/api/log-search/search",
            params={"dsl": 'severity=="high"; drop table security_events'},
            headers=self._h(self.admin_token),
        )
        assert r.status_code == 400

    def test_advanced_legacy_query_contract(self):
        # 旧测试契约：query=... 返回 200（非 401/403）
        r = self.client.get(
            "/api/log-search/search/advanced",
            params={"query": 'severity=="high"'},
            headers=self._h(self.admin_token),
        )
        assert r.status_code == 200

    # ── P0-4 导出 ─────────────────────────────────────────────
    def test_export_masked_and_audit(self):
        r = self.client.get(
            "/api/log-search/search/export",
            params={"masked": 1, "format": "json", "case_id": self.ca},
            headers=self._h(self.analyst_token),
        )
        assert r.status_code == 200
        body = b"".join(r.iter_bytes()).decode("utf-8")
        items = json.loads(body)
        assert len(items) == 2
        flat = json.dumps(items)
        assert "1.1.1.1" not in flat  # evidence 内 IP 已脱敏
        assert "8.8.8.8" not in flat
        # 审计落库
        with get_connection() as conn:
            row = conn.execute("SELECT * FROM export_audit_log ORDER BY id DESC LIMIT 1").fetchone()
        assert row is not None
        assert row["username"] == "analyst"
        assert row["masked"] == 1
        assert row["row_count"] == 2
        assert row["format"] == "json"

    def test_export_viewer_forced_masked(self):
        # viewer 明文导出被强制脱敏（审计 masked=1）
        r = self.client.get(
            "/api/log-search/search/export",
            params={"masked": 0, "format": "json"},
            headers=self._h(self.analyst_token),
        )
        assert r.status_code == 200
        with get_connection() as conn:
            row = conn.execute("SELECT * FROM export_audit_log ORDER BY id DESC LIMIT 1").fetchone()
        assert row["masked"] == 1

    def test_export_audits_admin_only(self):
        r = self.client.get("/api/log-search/export-audits", headers=self._h(self.analyst_token))
        assert r.status_code == 403
        r = self.client.get("/api/log-search/export-audits", headers=self._h(self.admin_token))
        assert r.status_code == 200

    def test_export_page_size_over_10000_400(self):
        r = self.client.get(
            "/api/log-search/search/export",
            params={"page_size": 20000},
            headers=self._h(self.admin_token),
        )
        assert r.status_code == 422  # FastAPI Query le 校验

    # ── P0-3 NL ───────────────────────────────────────────────
    def _mock_llm(self):
        """返回 ExitStack（含 AgentLLM 替身）作为上下文管理器。"""
        from contextlib import ExitStack
        from unittest.mock import patch

        class _FakeLLM:
            INTENT_MARKER = "请输出 JSON 查询意图"

            async def call(self, prompt, user=None, budget=None, **kwargs):
                if self.INTENT_MARKER in (prompt or ""):
                    return {
                        "content": json.dumps({
                            "filters": [{"field": "severity", "op": "=", "value": "high"}],
                            "time_range": {}, "sort": "timestamp DESC", "page_size": 50,
                            "summary_requested": True,
                        }),
                        "usage": {"total_tokens": 10}, "degraded": False, "error": None,
                    }
                return {"content": "测试摘要", "usage": {}, "degraded": False, "error": None}

        stack = ExitStack()
        stack.enter_context(patch("app.services.nl_query_guard.AgentLLM", _FakeLLM))
        stack.enter_context(patch("app.services.nl_log_search.AgentLLM", _FakeLLM))
        return stack

    def test_nl_preview_only(self):
        with self._mock_llm():
            r = self.client.post(
                "/api/ai/nl-log-search",
                json={"nl_text": "查高危日志", "preview_only": True},
                headers=self._h(self.analyst_token),
            )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["preview"] is True
        assert data["rows"] == []
        assert data["query_plan"] is not None
        assert data["audit_id"] is not None
        # preview 审计
        from app.models.nl_query_audit import NlQueryAudit

        audit = NlQueryAudit.get_by_id(data["audit_id"])
        assert audit["status"] == "preview"

    def test_nl_text_over_200_400(self):
        r = self.client.post(
            "/api/ai/nl-log-search",
            json={"nl_text": "查" * 201},
            headers=self._h(self.admin_token),
        )
        assert r.status_code == 200
        assert r.json()["code"] == 1
        assert "200" in r.json()["message"]

    def test_nl_forbidden_host_403(self):
        r = self.client.post(
            "/api/ai/nl-log-search",
            json={"nl_text": "查日志", "host_id": self.hb1},
            headers=self._h(self.analyst_token),
        )
        assert r.status_code == 403

    # ── P1-1 时间 ─────────────────────────────────────────────
    def test_time_parse_formats(self):
        from app.services.time_utils import parse_client_time

        assert parse_client_time("2026-07-14T09:00:00.000Z") == "2026-07-14 09:00:00"
        assert parse_client_time("2026-07-14 09:00:00") == "2026-07-14 09:00:00"
        assert parse_client_time("2026-07-14") == "2026-07-14 00:00:00"

    def test_search_time_range(self):
        r = self.client.get(
            "/api/log-search/search",
            params={"start_time": "2026-07-14T09:04:00.000Z", "end_time": "2026-07-14 09:06:00"},
            headers=self._h(self.analyst_token),
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["total"] == 1
        assert data["items"][0]["id"] == "e2"


if __name__ == "__main__":
    unittest.main(verbosity=2)
