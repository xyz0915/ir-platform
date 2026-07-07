#!/usr/bin/env python3
"""个人应急响应平台 — 综合测试套件.

测试范围:
  1. 后端数据库初始化 (13 张表、默认 admin、默认规则)
  2. API 接口 (认证、案件 CRUD、主机 CRUD、导入、分析、报告、规则)
  3. Agent (help、采集、JSON Schema 17 个顶层 key)
  4. 分析引擎 (画像、异常检测、时间线、风险评级)
  5. 前端构建 (npm install + npm run build)

运行方式:
    cd backend
    venv\\Scripts\\python.exe tests\\test_platform.py
"""

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# 确保后端目录在 Python 路径中
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

# 测试用临时数据库路径
TEST_DB_PATH = str(BACKEND_DIR / "data" / "test_ir_platform.db")


class TestDatabaseInit(unittest.TestCase):
    """测试数据库初始化."""

    @classmethod
    def setUpClass(cls):
        """测试类初始化：设置测试数据库路径并初始化."""
        # 删除旧的测试数据库
        db_path = Path(TEST_DB_PATH)
        if db_path.exists():
            db_path.unlink()

        # 设置环境变量使配置使用测试数据库
        os.environ["IR_TEST_DB"] = TEST_DB_PATH

        from app.config import settings
        settings.DB_PATH = TEST_DB_PATH

        # 确保数据目录存在
        Path(settings.DATA_DIR).mkdir(parents=True, exist_ok=True)
        Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
        Path(settings.AGENT_DIR).mkdir(parents=True, exist_ok=True)

        from app.database import init_db
        init_db()

    def test_01_all_tables_created(self):
        """验证 13 张表全部创建."""
        from app.config import settings
        conn = sqlite3.connect(settings.DB_PATH)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row[0] for row in cursor.fetchall()]
        conn.close()

        expected_tables = [
            "users", "cases", "hosts", "import_records",
            "host_profiles", "analysis_results", "abnormal_processes",
            "suspicious_connections", "suspicious_startup_items",
            "persistence_items", "timeline_events", "ioc_hits", "rules",
        ]
        for table in expected_tables:
            self.assertIn(table, tables, f"表 {table} 未创建")

    def test_02_default_admin_created(self):
        """验证默认 admin 用户已创建."""
        from app.models.user import User
        user = User.get_by_username("admin")
        self.assertIsNotNone(user, "默认 admin 用户未创建")
        self.assertEqual(user["username"], "admin")
        self.assertEqual(user["role"], "admin")
        self.assertIsNotNone(user["password_hash"])

    def test_03_default_admin_password_works(self):
        """验证 admin/admin123 密码可验证."""
        from app.services.auth_service import verify_password
        from app.models.user import User
        user = User.get_by_username("admin")
        self.assertTrue(
            verify_password("admin123", user["password_hash"]),
            "默认密码 admin123 验证失败",
        )

    def test_04_default_rules_imported(self):
        """验证默认规则已导入."""
        from app.models.rule import Rule
        rules = Rule.list()
        self.assertGreater(len(rules), 0, "默认规则未导入")
        # 验证规则覆盖多个类别
        categories = set(r.get("category", "") for r in rules)
        expected_categories = {"process", "network", "startup", "persistence", "ioc", "behavior"}
        for cat in expected_categories:
            self.assertIn(cat, categories, f"缺少类别 {cat} 的规则")

    def test_05_rules_have_valid_conditions(self):
        """验证规则的 condition 字段是有效 JSON."""
        from app.models.rule import Rule
        rules = Rule.list()
        for rule in rules:
            condition = rule.get("condition")
            self.assertIsInstance(condition, dict, f"规则 {rule['name']} 的 condition 不是字典")


class TestAPIAuth(unittest.TestCase):
    """测试认证 API."""

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from app.main import app
        cls.client = TestClient(app)
        cls.token = None

    def test_01_login_success(self):
        """测试 admin/admin123 登录成功."""
        response = self.client.post("/api/auth/login", json={
            "username": "admin",
            "password": "admin123",
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 0)
        self.assertIn("token", data["data"])
        self.assertEqual(data["data"]["user"]["username"], "admin")
        TestAPIAuth.token = data["data"]["token"]

    def test_02_login_wrong_password(self):
        """测试错误密码登录失败."""
        response = self.client.post("/api/auth/login", json={
            "username": "admin",
            "password": "wrongpassword",
        })
        self.assertEqual(response.status_code, 401)

    def test_03_login_nonexistent_user(self):
        """测试不存在的用户登录失败."""
        response = self.client.post("/api/auth/login", json={
            "username": "nonexistent",
            "password": "password",
        })
        self.assertEqual(response.status_code, 401)

    def test_04_get_me_with_token(self):
        """测试带 Token 获取当前用户."""
        response = self.client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {TestAPIAuth.token}"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 0)
        self.assertEqual(data["data"]["username"], "admin")

    def test_05_get_me_without_token(self):
        """测试不带 Token 获取当前用户失败."""
        response = self.client.get("/api/auth/me")
        self.assertEqual(response.status_code, 401)

    def test_06_health_check(self):
        """测试健康检查接口."""
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 0)
        self.assertEqual(data["data"]["status"], "ok")


class TestAPICases(unittest.TestCase):
    """测试案件 CRUD API."""

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from app.main import app
        cls.client = TestClient(app)
        # 登录获取 token
        response = cls.client.post("/api/auth/login", json={
            "username": "admin", "password": "admin123",
        })
        cls.token = response.json()["data"]["token"]
        cls.auth_headers = {"Authorization": f"Bearer {cls.token}"}
        cls.case_id = None

    def test_01_create_case(self):
        """测试创建案件."""
        response = self.client.post(
            "/api/cases",
            json={
                "name": "测试案件-001",
                "case_number": "CASE-2025-001",
                "description": "测试用案件",
            },
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 0)
        self.assertEqual(data["data"]["name"], "测试案件-001")
        self.assertEqual(data["data"]["case_number"], "CASE-2025-001")
        self.assertEqual(data["data"]["status"], "open")
        TestAPICases.case_id = data["data"]["id"]

    def test_02_create_case_duplicate_number(self):
        """测试重复案件编号失败."""
        response = self.client.post(
            "/api/cases",
            json={
                "name": "测试案件-重复",
                "case_number": "CASE-2025-001",
                "description": "重复编号",
            },
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 409)

    def test_03_list_cases(self):
        """测试案件列表."""
        response = self.client.get(
            "/api/cases?page=1&size=10",
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 0)
        self.assertIn("items", data["data"])
        self.assertIn("total", data["data"])
        self.assertGreaterEqual(data["data"]["total"], 1)

    def test_04_get_case_detail(self):
        """测试获取案件详情."""
        response = self.client.get(
            f"/api/cases/{self.case_id}",
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 0)
        self.assertEqual(data["data"]["id"], self.case_id)

    def test_05_update_case(self):
        """测试更新案件."""
        response = self.client.put(
            f"/api/cases/{self.case_id}",
            json={"name": "测试案件-已更新", "status": "closed"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 0)
        self.assertEqual(data["data"]["name"], "测试案件-已更新")
        self.assertEqual(data["data"]["status"], "closed")

    def test_06_search_cases(self):
        """测试案件搜索."""
        response = self.client.get(
            "/api/cases?search=已更新",
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertGreaterEqual(data["data"]["total"], 1)


class TestAPIHosts(unittest.TestCase):
    """测试主机 CRUD API."""

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from app.main import app
        cls.client = TestClient(app)
        response = cls.client.post("/api/auth/login", json={
            "username": "admin", "password": "admin123",
        })
        cls.token = response.json()["data"]["token"]
        cls.auth_headers = {"Authorization": f"Bearer {cls.token}"}

        # 创建案件用于测试主机
        response = cls.client.post(
            "/api/cases",
            json={"name": "主机测试案件", "case_number": "HOST-TEST-001"},
            headers=cls.auth_headers,
        )
        cls.case_id = response.json()["data"]["id"]
        cls.host_id = None

    def test_01_create_host(self):
        """测试添加主机."""
        response = self.client.post(
            f"/api/cases/{self.case_id}/hosts",
            json={
                "hostname": "TEST-HOST-001",
                "ip_address": "192.168.1.50",
                "os_type": "windows",
                "os_version": "Windows 10 Pro",
            },
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 0)
        self.assertEqual(data["data"]["hostname"], "TEST-HOST-001")
        self.assertEqual(data["data"]["status"], "pending")
        TestAPIHosts.host_id = data["data"]["id"]

    def test_02_list_hosts(self):
        """测试获取主机列表."""
        response = self.client.get(
            f"/api/cases/{self.case_id}/hosts",
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 0)
        self.assertGreaterEqual(len(data["data"]), 1)

    def test_03_get_host_detail(self):
        """测试获取主机详情."""
        response = self.client.get(
            f"/api/hosts/{self.host_id}",
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 0)
        self.assertEqual(data["data"]["id"], self.host_id)

    def test_04_get_nonexistent_host(self):
        """测试获取不存在的主机."""
        response = self.client.get(
            "/api/hosts/99999",
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 404)


class TestAPIImport(unittest.TestCase):
    """测试数据导入 API."""

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from app.main import app
        cls.client = TestClient(app)
        response = cls.client.post("/api/auth/login", json={
            "username": "admin", "password": "admin123",
        })
        cls.token = response.json()["data"]["token"]
        cls.auth_headers = {"Authorization": f"Bearer {cls.token}"}

        # 创建案件和主机
        response = cls.client.post(
            "/api/cases",
            json={"name": "导入测试案件", "case_number": "IMPORT-TEST-001"},
            headers=cls.auth_headers,
        )
        cls.case_id = response.json()["data"]["id"]

        response = cls.client.post(
            f"/api/cases/{cls.case_id}/hosts",
            json={"hostname": "IMPORT-HOST", "os_type": "windows"},
            headers=cls.auth_headers,
        )
        cls.host_id = response.json()["data"]["id"]

        # 加载 mock 数据
        mock_path = Path(__file__).parent / "mock_agent_data.json"
        with open(mock_path, "r", encoding="utf-8") as f:
            cls.mock_data = json.load(f)

    def test_01_import_valid_json(self):
        """测试导入有效的 Agent JSON."""
        json_bytes = json.dumps(self.mock_data).encode("utf-8")
        response = self.client.post(
            f"/api/hosts/{self.host_id}/import",
            files={"file": ("agent_output.json", json_bytes, "application/json")},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 0)
        self.assertEqual(data["data"]["status"], "success")

    def test_02_host_status_updated_after_import(self):
        """测试导入后主机状态更新为 imported."""
        response = self.client.get(
            f"/api/hosts/{self.host_id}",
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 200)
        host = response.json()["data"]
        self.assertEqual(host["status"], "imported")
        self.assertIsNotNone(host["raw_json_path"])

    def test_03_import_records_list(self):
        """测试获取导入记录列表."""
        response = self.client.get(
            f"/api/hosts/{self.host_id}/import-records",
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 0)
        self.assertGreaterEqual(len(data["data"]), 1)

    def test_04_import_invalid_json(self):
        """测试导入无效 JSON 失败."""
        response = self.client.post(
            f"/api/hosts/{self.host_id}/import",
            files={"file": ("bad.json", b"not a json", "application/json")},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 400)

    def test_05_import_to_nonexistent_host(self):
        """测试导入到不存在的主机."""
        json_bytes = json.dumps(self.mock_data).encode("utf-8")
        response = self.client.post(
            "/api/hosts/99999/import",
            files={"file": ("agent_output.json", json_bytes, "application/json")},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 404)


class TestAPIAnalysis(unittest.TestCase):
    """测试分析引擎 API."""

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from app.main import app
        cls.client = TestClient(app)
        response = cls.client.post("/api/auth/login", json={
            "username": "admin", "password": "admin123",
        })
        cls.token = response.json()["data"]["token"]
        cls.auth_headers = {"Authorization": f"Bearer {cls.token}"}

        # 创建案件和主机
        response = cls.client.post(
            "/api/cases",
            json={"name": "分析测试案件", "case_number": "ANALYSIS-TEST-001"},
            headers=cls.auth_headers,
        )
        cls.case_id = response.json()["data"]["id"]

        response = cls.client.post(
            f"/api/cases/{cls.case_id}/hosts",
            json={"hostname": "ANALYSIS-HOST", "os_type": "windows"},
            headers=cls.auth_headers,
        )
        cls.host_id = response.json()["data"]["id"]

        # 导入 mock 数据
        mock_path = Path(__file__).parent / "mock_agent_data.json"
        with open(mock_path, "r", encoding="utf-8") as f:
            mock_data = json.load(f)
        json_bytes = json.dumps(mock_data).encode("utf-8")
        cls.client.post(
            f"/api/hosts/{cls.host_id}/import",
            files={"file": ("agent_output.json", json_bytes, "application/json")},
            headers=cls.auth_headers,
        )

    def test_01_trigger_analysis(self):
        """测试触发分析."""
        response = self.client.post(
            f"/api/hosts/{self.host_id}/analyze",
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 0)
        result = data["data"]
        self.assertIn(result["risk_level"], ["critical", "high", "medium", "low", "info"])
        self.assertIsInstance(result["risk_score"], int)
        self.assertGreaterEqual(result["total_findings"], 0)

    def test_02_host_status_analyzed(self):
        """测试分析后主机状态更新为 analyzed."""
        response = self.client.get(
            f"/api/hosts/{self.host_id}",
            headers=self.auth_headers,
        )
        host = response.json()["data"]
        self.assertEqual(host["status"], "analyzed")

    def test_03_get_analysis_result(self):
        """测试获取分析结果."""
        response = self.client.get(
            f"/api/hosts/{self.host_id}/analysis",
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 0)
        self.assertIsNotNone(data["data"])
        self.assertIn("risk_level", data["data"])
        self.assertIn("risk_score", data["data"])

    def test_04_get_host_profile(self):
        """测试获取主机画像."""
        response = self.client.get(
            f"/api/hosts/{self.host_id}/profile",
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 0)
        self.assertIsNotNone(data["data"])

    def test_05_get_timeline(self):
        """测试获取时间线."""
        response = self.client.get(
            f"/api/hosts/{self.host_id}/timeline",
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 0)
        self.assertIsInstance(data["data"], list)

    def test_06_get_ioc_hits(self):
        """测试获取 IOC 命中."""
        response = self.client.get(
            f"/api/hosts/{self.host_id}/ioc-hits",
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 0)

    def test_07_get_persistence(self):
        """测试获取持久化痕迹."""
        response = self.client.get(
            f"/api/hosts/{self.host_id}/persistence",
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 0)

    def test_08_get_suspicious_connections(self):
        """测试获取可疑外连."""
        response = self.client.get(
            f"/api/hosts/{self.host_id}/suspicious-connections",
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 0)

    def test_09_get_abnormal_processes(self):
        """测试获取异常进程."""
        response = self.client.get(
            f"/api/hosts/{self.host_id}/abnormal-processes",
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 0)

    def test_10_get_startup_items(self):
        """测试获取可疑启动项."""
        response = self.client.get(
            f"/api/hosts/{self.host_id}/startup-items",
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 0)

    def test_11_analysis_detected_threats(self):
        """验证分析确实检测到了威胁."""
        # 获取异常进程 - mock 数据包含 powershell -enc
        response = self.client.get(
            f"/api/hosts/{self.host_id}/abnormal-processes",
            headers=self.auth_headers,
        )
        processes = response.json()["data"]
        self.assertGreater(len(processes), 0, "应检测到异常进程")

        # 获取可疑外连 - mock 数据包含连接到 4444 端口
        response = self.client.get(
            f"/api/hosts/{self.host_id}/suspicious-connections",
            headers=self.auth_headers,
        )
        connections = response.json()["data"]
        self.assertGreater(len(connections), 0, "应检测到可疑外连")

        # 获取持久化痕迹
        response = self.client.get(
            f"/api/hosts/{self.host_id}/persistence",
            headers=self.auth_headers,
        )
        persistence = response.json()["data"]
        self.assertGreater(len(persistence), 0, "应检测到持久化痕迹")

    def test_12_risk_level_is_high(self):
        """验证风险评估结果为高危或严重."""
        response = self.client.get(
            f"/api/hosts/{self.host_id}/analysis",
            headers=self.auth_headers,
        )
        result = response.json()["data"]
        # mock 数据包含 critical 级别威胁，风险等级应为 high 或 critical
        self.assertIn(
            result["risk_level"],
            ["critical", "high"],
            f"风险等级应为 high 或 critical，实际为 {result['risk_level']}",
        )
        self.assertGreater(result["risk_score"], 0, "风险分数应大于 0")

    def test_13_reanalyze_overwrites_old(self):
        """测试重新分析覆盖旧结果."""
        # 再次触发分析
        response = self.client.post(
            f"/api/hosts/{self.host_id}/analyze",
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 200)

        # 验证结果仍然存在
        response = self.client.get(
            f"/api/hosts/{self.host_id}/analysis",
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.json()["data"])


class TestAPIReport(unittest.TestCase):
    """测试报告生成 API."""

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from app.main import app
        cls.client = TestClient(app)
        response = cls.client.post("/api/auth/login", json={
            "username": "admin", "password": "admin123",
        })
        cls.token = response.json()["data"]["token"]
        cls.auth_headers = {"Authorization": f"Bearer {cls.token}"}

        # 创建完整流程：案件 → 主机 → 导入 → 分析
        response = cls.client.post(
            "/api/cases",
            json={"name": "报告测试案件", "case_number": "REPORT-TEST-001"},
            headers=cls.auth_headers,
        )
        cls.case_id = response.json()["data"]["id"]

        response = cls.client.post(
            f"/api/cases/{cls.case_id}/hosts",
            json={"hostname": "REPORT-HOST", "os_type": "windows"},
            headers=cls.auth_headers,
        )
        cls.host_id = response.json()["data"]["id"]

        mock_path = Path(__file__).parent / "mock_agent_data.json"
        with open(mock_path, "r", encoding="utf-8") as f:
            mock_data = json.load(f)
        json_bytes = json.dumps(mock_data).encode("utf-8")
        cls.client.post(
            f"/api/hosts/{cls.host_id}/import",
            files={"file": ("agent_output.json", json_bytes, "application/json")},
            headers=cls.auth_headers,
        )
        cls.client.post(
            f"/api/hosts/{cls.host_id}/analyze",
            headers=cls.auth_headers,
        )

    def test_01_generate_html_report(self):
        """测试生成 HTML 报告."""
        response = self.client.get(
            f"/api/hosts/{self.host_id}/report",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers.get("content-type", ""))
        html_content = response.text
        self.assertIn("应急响应", html_content)
        self.assertIn("风险评估", html_content)

    def test_02_html_report_contains_threats(self):
        """验证 HTML 报告包含威胁信息."""
        response = self.client.get(
            f"/api/hosts/{self.host_id}/report",
        )
        html = response.text
        # 报告应包含异常进程或可疑外连
        self.assertTrue(
            "异常进程" in html or "可疑外连" in html or "持久化" in html,
            "HTML 报告应包含威胁信息",
        )

    def test_03_report_for_nonexistent_host(self):
        """测试不存在主机的报告."""
        response = self.client.get("/api/hosts/99999/report")
        self.assertEqual(response.status_code, 404)


class TestAPIRules(unittest.TestCase):
    """测试规则管理 API."""

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from app.main import app
        cls.client = TestClient(app)
        response = cls.client.post("/api/auth/login", json={
            "username": "admin", "password": "admin123",
        })
        cls.token = response.json()["data"]["token"]
        cls.auth_headers = {"Authorization": f"Bearer {cls.token}"}

    def test_01_list_rules(self):
        """测试获取规则列表."""
        response = self.client.get(
            "/api/rules",
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 0)
        self.assertGreater(len(data["data"]), 0)

    def test_02_list_rules_by_category(self):
        """测试按类别筛选规则."""
        response = self.client.get(
            "/api/rules?category=process",
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        for rule in data["data"]:
            self.assertEqual(rule["category"], "process")

    def test_03_create_rule(self):
        """测试创建新规则."""
        response = self.client.post(
            "/api/rules",
            json={
                "name": "test_custom_rule",
                "category": "process",
                "rule_type": "regex",
                "condition": {"field": "command_line", "pattern": "test_malware", "flags": "ignorecase"},
                "severity": "medium",
                "description": "Test custom rule",
            },
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 0)
        self.assertEqual(data["data"]["name"], "test_custom_rule")

    def test_04_update_rule(self):
        """测试更新规则."""
        # 先创建规则
        response = self.client.post(
            "/api/rules",
            json={
                "name": "test_update_rule",
                "category": "network",
                "rule_type": "list",
                "condition": {"field": "remote_port", "values": [9999]},
                "severity": "low",
            },
            headers=self.auth_headers,
        )
        rule_id = response.json()["data"]["id"]

        # 更新规则
        response = self.client.put(
            f"/api/rules/{rule_id}",
            json={"enabled": False, "severity": "high"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 0)
        self.assertFalse(data["data"]["enabled"])
        self.assertEqual(data["data"]["severity"], "high")


class TestAnalysisEngine(unittest.TestCase):
    """测试分析引擎各模块."""

    def test_01_profile_builder(self):
        """测试主机画像构建器."""
        from app.analysis.profile_builder import ProfileBuilder
        mock_path = Path(__file__).parent / "mock_agent_data.json"
        with open(mock_path, "r", encoding="utf-8") as f:
            raw_data = json.load(f)

        profile = ProfileBuilder.build(raw_data)
        self.assertIn("cpu_info", profile)
        self.assertIn("memory_info", profile)
        self.assertIn("disk_info", profile)
        self.assertIn("network_info", profile)
        self.assertIn("installed_software", profile)
        self.assertIn("user_accounts", profile)
        self.assertIn("security_products", profile)
        self.assertIn("system_summary", profile)

        # 验证 CPU 信息
        cpu_info = json.loads(profile["cpu_info"])
        self.assertEqual(cpu_info["model"], "Intel i7-10700")

    def test_02_anomaly_detector_processes(self):
        """测试异常进程检测."""
        from app.analysis.anomaly_detector import AnomalyDetector
        mock_path = Path(__file__).parent / "mock_agent_data.json"
        with open(mock_path, "r", encoding="utf-8") as f:
            raw_data = json.load(f)

        # 使用空规则列表测试不崩溃
        results = AnomalyDetector.detect_processes(raw_data, [])
        self.assertIsInstance(results, list)

        # 使用默认规则测试
        from app.rules.rule_engine import RuleEngine
        rules = RuleEngine.load_rules()
        results = AnomalyDetector.detect_processes(raw_data, rules)
        # mock 数据包含 powershell -enc，应检测到
        self.assertGreater(len(results), 0, "应检测到异常进程")

    def test_03_anomaly_detector_connections(self):
        """测试可疑外连检测."""
        from app.analysis.anomaly_detector import AnomalyDetector
        mock_path = Path(__file__).parent / "mock_agent_data.json"
        with open(mock_path, "r", encoding="utf-8") as f:
            raw_data = json.load(f)

        from app.rules.rule_engine import RuleEngine
        rules = RuleEngine.load_rules()
        results = AnomalyDetector.detect_connections(raw_data, rules)
        # mock 数据包含连接到 4444 端口，应检测到
        self.assertGreater(len(results), 0, "应检测到可疑外连")

    def test_04_timeline_builder(self):
        """测试时间线构建."""
        from app.analysis.timeline_builder import TimelineBuilder
        mock_path = Path(__file__).parent / "mock_agent_data.json"
        with open(mock_path, "r", encoding="utf-8") as f:
            raw_data = json.load(f)

        events = TimelineBuilder.build(raw_data)
        self.assertIsInstance(events, list)
        self.assertGreater(len(events), 0, "应构建出时间线事件")

        # 验证排序
        timestamps = [e.get("timestamp", "") for e in events]
        self.assertEqual(timestamps, sorted(timestamps), "时间线事件应按时间排序")

    def test_05_persistence_finder(self):
        """测试持久化痕迹查找."""
        from app.analysis.persistence_finder import PersistenceFinder
        mock_path = Path(__file__).parent / "mock_agent_data.json"
        with open(mock_path, "r", encoding="utf-8") as f:
            raw_data = json.load(f)

        items = PersistenceFinder.find_all(raw_data)
        self.assertGreater(len(items), 0, "应找到持久化痕迹")

        # 验证包含 WMI 订阅
        types = [item.get("type") for item in items]
        self.assertIn("wmi", types, "应包含 WMI 事件订阅")

    def test_06_risk_assessor(self):
        """测试风险评估器."""
        from app.analysis.risk_assessor import RiskAssessor

        findings = {
            "abnormal_processes": [
                {"severity": "critical"},
                {"severity": "high"},
            ],
            "suspicious_connections": [
                {"severity": "critical"},
            ],
            "suspicious_startup_items": [],
            "persistence_items": [
                {"is_suspicious": True, "severity": "high"},
            ],
            "ioc_hits": [
                {"severity": "critical"},
            ],
            "timeline_events": [],
        }

        result = RiskAssessor.assess(findings)
        self.assertIn(result["risk_level"], ["critical", "high"])
        self.assertGreater(result["risk_score"], 0)
        self.assertGreater(result["total_findings"], 0)
        self.assertIsInstance(result["summary"], str)
        self.assertIsInstance(result["details"], dict)

    def test_07_risk_assessor_empty_findings(self):
        """测试无发现时的风险评估."""
        from app.analysis.risk_assessor import RiskAssessor

        findings = {
            "abnormal_processes": [],
            "suspicious_connections": [],
            "suspicious_startup_items": [],
            "persistence_items": [],
            "ioc_hits": [],
            "timeline_events": [],
        }

        result = RiskAssessor.assess(findings)
        self.assertEqual(result["risk_level"], "info")
        self.assertEqual(result["risk_score"], 0)
        self.assertEqual(result["total_findings"], 0)

    def test_08_rule_engine_regex(self):
        """测试规则引擎正则匹配."""
        from app.rules.rule_engine import RuleEngine

        rule = {
            "name": "test_regex",
            "rule_type": "regex",
            "condition": {"field": "command_line", "pattern": "powershell.*-enc", "flags": "ignorecase"},
            "severity": "high",
        }

        item = {"command_line": "powershell.exe -enc SQBFAFgA"}
        self.assertTrue(RuleEngine.match_rule(item, rule))

        item2 = {"command_line": "notepad.exe"}
        self.assertFalse(RuleEngine.match_rule(item2, rule))

    def test_09_rule_engine_list(self):
        """测试规则引擎列表匹配."""
        from app.rules.rule_engine import RuleEngine

        rule = {
            "name": "test_list",
            "rule_type": "list",
            "condition": {"field": "remote_port", "values": [4444, 6667], "match_mode": "exact"},
            "severity": "critical",
        }

        item = {"remote_port": 4444}
        self.assertTrue(RuleEngine.match_rule(item, rule))

        item2 = {"remote_port": 80}
        self.assertFalse(RuleEngine.match_rule(item2, rule))

    def test_10_rule_engine_threshold(self):
        """测试规则引擎阈值检测."""
        from app.rules.rule_engine import RuleEngine

        rule = {
            "name": "test_threshold",
            "rule_type": "threshold",
            "condition": {"field": "connection_count", "operator": ">", "value": 50},
            "severity": "medium",
        }

        item = {"connection_count": 60}
        self.assertTrue(RuleEngine.match_rule(item, rule))

        item2 = {"connection_count": 30}
        self.assertFalse(RuleEngine.match_rule(item2, rule))

    def test_11_rule_engine_behavior_orphan(self):
        """测试规则引擎行为检测 - 孤立进程."""
        from app.rules.rule_engine import RuleEngine

        rule = {
            "name": "test_orphan",
            "rule_type": "behavior",
            "condition": {"pattern": "orphan_process"},
            "severity": "medium",
        }

        item = {"ppid": 0}
        self.assertTrue(RuleEngine.match_rule(item, rule))

        item2 = {"ppid": 100}
        self.assertFalse(RuleEngine.match_rule(item2, rule))

    def test_12_ioc_checker(self):
        """测试 IOC 检测器."""
        from app.analysis.ioc_checker import IocChecker
        mock_path = Path(__file__).parent / "mock_agent_data.json"
        with open(mock_path, "r", encoding="utf-8") as f:
            raw_data = json.load(f)

        from app.rules.rule_engine import RuleEngine
        ioc_rules = RuleEngine.load_rules(category="ioc")
        hits = IocChecker.check(raw_data, ioc_rules)
        # mock 数据包含恶意 IP 185.220.101.1
        self.assertGreater(len(hits), 0, "应检测到 IOC 命中")


class TestAgent(unittest.TestCase):
    """测试 Agent 采集端."""

    @classmethod
    def setUpClass(cls):
        cls.agent_dir = BACKEND_DIR.parent / "agent"
        cls.python_exe = str(BACKEND_DIR / "venv" / "Scripts" / "python.exe")
        if not Path(cls.python_exe).exists():
            cls.python_exe = sys.executable

    def test_01_agent_help(self):
        """测试 Agent --help."""
        result = subprocess.run(
            [self.python_exe, str(self.agent_dir / "agent.py"), "--help"],
            capture_output=True, text=True, timeout=30,
            cwd=str(self.agent_dir),
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("--output", result.stdout)
        self.assertIn("--collect", result.stdout)

    def test_02_agent_collection(self):
        """测试 Agent 采集并输出 JSON."""
        output_file = str(self.agent_dir / "test_output.json")
        result = subprocess.run(
            [self.python_exe, str(self.agent_dir / "agent.py"),
             "-o", output_file, "-c", "system_info"],
            capture_output=True, text=True, timeout=60,
            cwd=str(self.agent_dir),
        )
        self.assertEqual(result.returncode, 0, f"Agent 采集失败: {result.stderr}")

        # 验证输出文件存在
        self.assertTrue(Path(output_file).exists(), "Agent 输出文件不存在")

        # 验证 JSON 格式
        with open(output_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        # 验证 17 个顶层 key
        expected_keys = [
            "metadata", "system_info", "users", "processes", "services",
            "startup_items", "network", "files", "registry", "logs",
            "security", "browser", "usb", "remote_control", "persistence",
            "ioc", "timeline",
        ]
        for key in expected_keys:
            self.assertIn(key, data, f"Agent 输出缺少顶层 key: {key}")

        # 验证 metadata
        self.assertIn("agent_version", data["metadata"])
        self.assertIn("collection_time", data["metadata"])
        self.assertIn("platform", data["metadata"])
        self.assertIn("hostname", data["metadata"])

        # 验证 system_info 有数据
        self.assertIsInstance(data["system_info"], dict)
        self.assertIn("hostname", data["system_info"])

    def test_03_agent_output_validates_schema(self):
        """测试 Agent 输出能通过 Pydantic Schema 校验."""
        from app.schemas.agent_data import AgentData

        output_file = self.agent_dir / "test_output.json"
        if not output_file.exists():
            self.skipTest("Agent 输出文件不存在，跳过 Schema 校验")

        with open(output_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        # 应该能通过校验
        try:
            agent_data = AgentData(**data)
            self.assertIsNotNone(agent_data)
        except Exception as exc:
            self.fail(f"Agent 输出未通过 Schema 校验: {exc}")


class TestFrontendBuild(unittest.TestCase):
    """测试前端构建."""

    @classmethod
    def setUpClass(cls):
        cls.frontend_dir = BACKEND_DIR.parent / "frontend"
        cls.node_exe = r"C:\Users\xyz\.workbuddy\binaries\node\versions\22.22.2\node.exe"
        cls.npm_cmd = cls.node_exe.replace("node.exe", "npm.cmd")
        if not Path(cls.npm_cmd).exists():
            # 尝试 npx
            cls.npm_cmd = None

    def test_01_npm_install(self):
        """测试 npm install."""
        if not Path(self.node_exe).exists():
            self.skipTest("Node.js 不可用，跳过前端测试")

        # 检查 node_modules 是否已存在
        node_modules = self.frontend_dir / "node_modules"
        if node_modules.exists():
            self.skipTest("node_modules 已存在，跳过安装")

        result = subprocess.run(
            [self.npm_cmd or "npm", "install"],
            capture_output=True, text=True, timeout=300,
            cwd=str(self.frontend_dir),
            shell=True,
        )
        self.assertEqual(result.returncode, 0, f"npm install 失败: {result.stderr}")

    def test_02_npm_build(self):
        """测试 npm run build."""
        if not Path(self.node_exe).exists():
            self.skipTest("Node.js 不可用，跳过前端测试")

        node_modules = self.frontend_dir / "node_modules"
        if not node_modules.exists():
            self.skipTest("node_modules 不存在，跳过构建")

        result = subprocess.run(
            [self.npm_cmd or "npm", "run", "build"],
            capture_output=True, text=True, timeout=120,
            cwd=str(self.frontend_dir),
            shell=True,
        )
        self.assertEqual(result.returncode, 0, f"npm run build 失败: {result.stderr}")

        # 验证 dist 目录存在
        dist_dir = self.frontend_dir / "dist"
        self.assertTrue(dist_dir.exists(), "构建后 dist 目录不存在")
        self.assertTrue((dist_dir / "index.html").exists(), "构建后 index.html 不存在")


def run_tests():
    """运行所有测试并输出报告."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # 按顺序添加测试类
    test_classes = [
        TestDatabaseInit,
        TestAPIAuth,
        TestAPICases,
        TestAPIHosts,
        TestAPIImport,
        TestAPIAnalysis,
        TestAPIReport,
        TestAPIRules,
        TestAnalysisEngine,
        TestAgent,
        TestFrontendBuild,
    ]

    for cls in test_classes:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result


if __name__ == "__main__":
    print("=" * 70)
    print("  个人应急响应平台 — 综合测试套件")
    print("=" * 70)
    print()

    result = run_tests()

    print()
    print("=" * 70)
    print(f"  测试结果: {result.testsRun - len(result.failures) - len(result.errors)}/{result.testsRun} 通过")
    print(f"  失败: {len(result.failures)}  错误: {len(result.errors)}")
    print("=" * 70)

    sys.exit(0 if result.wasSuccessful() else 1)
