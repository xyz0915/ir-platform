"""AI分析 API 端点测试套件.

测试范围:
    - Profile 管理端点 (CRUD + activate)
    - AI 分析提交 → 任务查询
    - 报告查询 (最新/版本列表/指定版本/版本对比/PDF)
    - 审计日志查询
    - Token 统计
    - 向后兼容端点 (config/toggle)
    - 连接测试
"""

import json
import os
import unittest

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

TEST_DB_PATH = str(BACKEND_DIR / "data" / "test_ai_api.db")


class TestAiApiEndpoints(unittest.TestCase):
    """测试 AI 分析 API 端点 (至少 14 个)."""

    @classmethod
    def setUpClass(cls):
        """设置测试环境."""
        db_path = Path(TEST_DB_PATH)
        if db_path.exists():
            db_path.unlink()

        from app.config import settings
        settings.DB_PATH = TEST_DB_PATH

        Path(settings.DATA_DIR).mkdir(parents=True, exist_ok=True)
        Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
        Path(settings.AGENT_DIR).mkdir(parents=True, exist_ok=True)

        from app.database import init_db
        init_db()

        from fastapi.testclient import TestClient
        from app.main import app
        cls.client = TestClient(app)

        # 登录获取 token
        resp = cls.client.post("/api/auth/login", json={
            "username": "admin",
            "password": "admin123",
        })
        cls.token = resp.json()["data"]["token"]
        cls.headers = {"Authorization": f"Bearer {cls.token}"}

        # 创建案件和主机
        resp = cls.client.post("/api/cases", json={
            "name": "AI API 测试案件",
            "case_number": "AI-API-TEST",
        }, headers=cls.headers)
        cls.case_id = resp.json()["data"]["id"]

        resp = cls.client.post(f"/api/cases/{cls.case_id}/hosts", json={
            "hostname": "AI-API-HOST",
            "ip_address": "10.0.0.20",
            "os_type": "windows",
        }, headers=cls.headers)
        cls.host_id = resp.json()["data"]["id"]

    # ============================================================
    # Profile 管理端点
    # ============================================================

    def test_01_list_profiles_empty(self):
        """GET /api/ai/profiles — 初始状态应返回空列表."""
        resp = self.client.get("/api/ai/profiles", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertEqual(data["data"]["total"], 0)
        self.assertIsNone(data["data"]["active_id"])

    def test_02_create_profile(self):
        """POST /api/ai/profiles — 创建 Profile."""
        resp = self.client.post("/api/ai/profiles", json={
            "profile_name": "测试Profile",
            "provider": "openai",
            "api_base_url": "https://api.openai.com/v1",
            "api_key": "sk-test-key-for-profile",
            "model_name": "gpt-4o",
            "max_tokens": 4096,
            "temperature": 0.3,
        }, headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertEqual(data["data"]["profile_name"], "测试Profile")
        self.assertEqual(data["data"]["is_active"], 1)
        # API Key 应脱敏
        self.assertIn("api_key_masked", data["data"])
        self.assertNotIn("api_key", data["data"])

    def test_03_list_profiles_with_data(self):
        """GET /api/ai/profiles — 现在应有1个Profile."""
        resp = self.client.get("/api/ai/profiles", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["data"]["total"], 1)
        self.assertIsNotNone(data["data"]["active_id"])

    def test_04_create_second_profile(self):
        """POST /api/ai/profiles — 创建第二个 Profile."""
        resp = self.client.post("/api/ai/profiles", json={
            "profile_name": "Azure备份",
            "provider": "azure",
            "api_base_url": "https://my.openai.azure.com",
            "api_key": "sk-azure-key-111",
            "model_name": "gpt-4",
        }, headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertEqual(data["data"]["is_active"], 0)

    def test_05_activate_profile(self):
        """POST /api/ai/profiles/{id}/activate — 激活指定 Profile."""
        resp = self.client.post("/api/ai/profiles/2/activate", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertEqual(data["data"]["is_active"], 1)

        # 验证互斥：Profile 1 应为非激活
        resp2 = self.client.get("/api/ai/profiles", headers=self.headers)
        profiles = resp2.json()["data"]["items"]
        p1 = next(p for p in profiles if p["id"] == 1)
        p2 = next(p for p in profiles if p["id"] == 2)
        self.assertEqual(p1["is_active"], 0)
        self.assertEqual(p2["is_active"], 1)

    def test_06_update_profile(self):
        """PUT /api/ai/profiles/{id} — 更新 Profile."""
        resp = self.client.put("/api/ai/profiles/1", json={
            "profile_name": "测试Profile-已更新",
            "model_name": "gpt-4o-mini",
        }, headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertEqual(data["data"]["profile_name"], "测试Profile-已更新")
        self.assertEqual(data["data"]["model_name"], "gpt-4o-mini")

    def test_07_delete_profile(self):
        """DELETE /api/ai/profiles/{id} — 删除非激活 Profile."""
        # 先创建第三个，然后删除1（非激活的）
        self.client.post("/api/ai/profiles", json={
            "profile_name": "待删除配置",
            "provider": "anthropic",
            "api_base_url": "https://api.anthropic.com",
            "api_key": "sk-delete-me",
            "model_name": "claude-3",
        }, headers=self.headers)

        resp = self.client.delete("/api/ai/profiles/1", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)

    def test_08_delete_active_profile_blocked(self):
        """DELETE /api/ai/profiles/{id} — 删除激活 Profile 应被阻止."""
        resp = self.client.delete("/api/ai/profiles/2", headers=self.headers)
        self.assertEqual(resp.status_code, 409)

    # ============================================================
    # AI 配置向后兼容端点
    # ============================================================

    def test_09_get_ai_config(self):
        """GET /api/ai/config — 旧版获取配置."""
        resp = self.client.get("/api/ai/config", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertIsNotNone(data["data"])

    def test_10_save_ai_config(self):
        """POST /api/ai/config — 旧版保存配置."""
        resp = self.client.post("/api/ai/config", json={
            "api_base_url": "https://new-host.example.com",
            "api_key": "sk-new-key",
            "model_name": "gpt-4o",
            "enabled": 1,
        }, headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)

    def test_11_toggle_ai(self):
        """POST /api/ai/toggle — AI 开关."""
        resp = self.client.post("/api/ai/toggle", json={
            "enabled": 1,
        }, headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)

    # ============================================================
    # AI 分析任务端点
    # ============================================================

    def test_12_submit_analysis(self):
        """POST /api/ai/analyze/{host_id} — 提交分析任务."""
        resp = self.client.post(
            f"/api/ai/analyze/{self.host_id}?masked_mode=1",
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertIn("task_id", data["data"])
        self.assertEqual(data["data"]["host_id"], self.host_id)
        self.assertEqual(data["data"]["status"], "pending")
        TestAiApiEndpoints.task_id = data["data"]["task_id"]

    def test_13_get_task_status(self):
        """GET /api/ai/tasks/{task_id} — 查询任务状态."""
        task_id = getattr(TestAiApiEndpoints, "task_id", 1)
        resp = self.client.get(f"/api/ai/tasks/{task_id}", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertIn("status", data["data"])
        self.assertIn("progress", data["data"])

    def test_14_list_tasks(self):
        """GET /api/ai/tasks — 列出所有任务."""
        resp = self.client.get("/api/ai/tasks", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertIn("items", data["data"])

    def test_15_list_tasks_by_host(self):
        """GET /api/ai/tasks?host_id=X — 按主机筛选."""
        resp = self.client.get(
            f"/api/ai/tasks?host_id={self.host_id}",
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        for item in data["data"]["items"]:
            self.assertEqual(item["host_id"], self.host_id)

    def test_16_cancel_task(self):
        """POST /api/ai/tasks/{task_id}/cancel — 取消任务."""
        task_id = getattr(TestAiApiEndpoints, "task_id", 1)
        resp = self.client.post(
            f"/api/ai/tasks/{task_id}/cancel",
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertEqual(data["data"]["status"], "cancelled")

    # ============================================================
    # AI 报告端点
    # ============================================================

    def test_17_get_ai_report_empty(self):
        """GET /api/ai/report/{host_id} — 无报告时返回空."""
        resp = self.client.get(
            f"/api/ai/report/{self.host_id}",
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertIsNone(data["data"])

    def test_18_list_report_versions_empty(self):
        """GET /api/ai/report/{host_id}/versions — 无版本时返回空列表."""
        resp = self.client.get(
            f"/api/ai/report/{self.host_id}/versions",
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertEqual(data["data"]["total"], 0)

    def test_19_get_report_version_nonexistent(self):
        """GET /api/ai/report/{host_id}/versions/{v} — 不存在的版本返回404."""
        resp = self.client.get(
            f"/api/ai/report/{self.host_id}/versions/999",
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 404)

    # ============================================================
    # 审计日志端点
    # ============================================================

    def test_20_list_audit_logs(self):
        """GET /api/ai/audit-logs — 分页查询审计日志."""
        resp = self.client.get(
            "/api/ai/audit-logs?page=1&page_size=10",
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertIn("items", data["data"])
        self.assertIn("total", data["data"])

    def test_21_get_audit_log_detail_nonexistent(self):
        """GET /api/ai/audit-logs/{id} — 不存在的日志返回404."""
        resp = self.client.get(
            "/api/ai/audit-logs/99999",
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 404)

    # ============================================================
    # 统计端点
    # ============================================================

    def test_22_get_token_stats(self):
        """GET /api/ai/stats/tokens — Token统计."""
        resp = self.client.get(
            "/api/ai/stats/tokens?days=30",
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertIn("items", data["data"])

    def test_23_get_stats_summary(self):
        """GET /api/ai/stats/summary — 汇总统计."""
        resp = self.client.get(
            "/api/ai/stats/summary",
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertIn("total_tokens", data["data"])

    # ============================================================
    # 连接测试端点
    # ============================================================

    def test_24_test_connection_via_profile(self):
        """POST /api/ai/test-connection — 通过 profile_id 测试连接."""
        resp = self.client.post("/api/ai/test-connection", json={
            "profile_id": 2,
        }, headers=self.headers)
        # 预期失败（无法真正连接外部API），但不应500
        self.assertIn(resp.status_code, [200, 502])
        data = resp.json()
        self.assertIn("code", data)
        # success 可能是 False (连接不通)，但不应该崩溃
        self.assertIn("data", data)

    # ============================================================
    # 认证验证
    # ============================================================

    def test_25_unauthenticated_requests_blocked(self):
        """所有 AI API 端点应要求认证."""
        endpoints = [
            ("GET", "/api/ai/profiles"),
            ("GET", "/api/ai/config"),
            ("GET", "/api/ai/audit-logs"),
        ]
        for method, path in endpoints:
            if method == "GET":
                resp = self.client.get(path)
            else:
                resp = self.client.post(path)
            self.assertEqual(resp.status_code, 401, f"{method} {path} 应要求认证")


if __name__ == "__main__":
    unittest.main(verbosity=2)
