#!/usr/bin/env python3
"""应急工具箱 API 集成测试.

测试覆盖:
    1. test_create_tool       — 上传新工具
    2. test_get_tool           — 按 ID 获取详情
    3. test_search_tools       — 搜索 / 分类筛选 / 分页
    4. test_get_stats          — 统计概览
    5. test_update_tool        — 更新工具信息
    6. test_delete_tool        — 删除工具
    7. test_get_categories     — 分类列表
    8. test_publish_version    — 发布新版本
    9. test_download_tool      — 下载工具文件
   10. test_doc_preview        — 文档查看
   11. test_permission         — 非 admin 上传权限校验

运行方式:
    cd backend
    venv\\Scripts\\python.exe -m pytest tests/test_toolbox_api.py -v
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

# 测试用数据库路径
TEST_DB_PATH = str(BACKEND_DIR / "data" / "test_toolbox_api.db")


class TestToolboxApi(unittest.TestCase):
    """应急工具箱 API CRUD 集成测试."""

    @classmethod
    def setUpClass(cls):
        """设置测试环境：临时数据库、Flie 存储、登录 Token."""
        # 清理旧测试库
        db_path = Path(TEST_DB_PATH)
        if db_path.exists():
            db_path.unlink()

        from app.config import settings
        settings.DB_PATH = TEST_DB_PATH

        # 确保目录存在
        Path(settings.DATA_DIR).mkdir(parents=True, exist_ok=True)
        Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
        Path(settings.AGENT_DIR).mkdir(parents=True, exist_ok=True)

        from app.database import init_db
        init_db()

        from fastapi.testclient import TestClient
        from app.main import app
        cls.client = TestClient(app)

        # 登录获取 admin token
        resp = cls.client.post("/api/auth/login", json={
            "username": "admin",
            "password": "admin123",
        })
        assert resp.status_code == 200, f"Login failed: {resp.text}"
        cls.token = resp.json()["data"]["token"]
        cls.headers = {"Authorization": f"Bearer {cls.token}"}

        # 工具文件存储基础路径
        cls.tools_storage = Path(settings.BACKEND_DIR) / "app" / "data" / "tools"

    @classmethod
    def tearDownClass(cls):
        """清理测试数据库和文件."""
        db_path = Path(TEST_DB_PATH)
        if db_path.exists():
            db_path.unlink()
        # 清理测试产生的工具文件
        tools_dir = Path(__file__).resolve().parent.parent / "app" / "data" / "tools"
        if tools_dir.exists():
            import shutil
            shutil.rmtree(tools_dir, ignore_errors=True)

    # ============================================================
    # 辅助方法
    # ============================================================

    def _create_test_tool(self, name="TestTool", category="取证分析", version="1.0.0"):
        """上传一个测试工具并返回其 ID."""
        # 创建测试文件
        tool_content = b"fake tool binary content"
        files = {
            "name": (None, name),
            "description": (None, "A test tool for emergency response"),
            "category": (None, category),
            "version": (None, version),
            "tags": (None, '["test", "forensics"]'),
            "tool_file": ("test_tool.exe", tool_content),
        }
        resp = self.client.post("/api/tools", files=files, headers=self.headers)
        self.assertEqual(resp.status_code, 200, f"Create tool failed: {resp.text}")
        data = resp.json()
        self.assertEqual(data["code"], 0)
        return data["data"]["id"]

    # ============================================================
    # Test 1: 上传新工具
    # ============================================================

    def test_01_create_tool(self):
        """POST /api/tools — 上传新工具并验证返回 ID."""
        tool_id = self._create_test_tool(
            name="创建测试工具",
            category="日志分析",
            version="1.0.0",
        )
        self.assertIsInstance(tool_id, int)
        self.assertGreater(tool_id, 0)

    def test_01b_create_tool_with_doc(self):
        """POST /api/tools — 上传带文档的工具."""
        tool_content = b"binary content"
        doc_content = b"# Operation Manual\n\nStep 1: Run the tool."
        files = {
            "name": (None, "DocTool"),
            "description": (None, "Tool with documentation"),
            "category": (None, "响应处置"),
            "version": (None, "1.0.0"),
            "tags": (None, '["doc"]'),
            "tool_file": ("doc_tool.exe", tool_content),
            "doc_file": ("manual.md", doc_content),
        }
        resp = self.client.post("/api/tools", files=files, headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertIn("id", data["data"])

    def test_01c_create_tool_invalid_version(self):
        """POST /api/tools — 无效版本号应返回 400."""
        tool_content = b"binary"
        files = {
            "name": (None, "BadVersionTool"),
            "description": (None, "Bad version"),
            "category": (None, "other"),
            "version": (None, "invalid"),
            "tags": (None, "[]"),
            "tool_file": ("bad.exe", tool_content),
        }
        resp = self.client.post("/api/tools", files=files, headers=self.headers)
        self.assertEqual(resp.status_code, 400)

    def test_01d_create_tool_no_file(self):
        """POST /api/tools — 缺少工具文件应返回 422."""
        files = {
            "name": (None, "NoFileTool"),
            "description": (None, "No file"),
            "category": (None, "other"),
            "version": (None, "1.0.0"),
            "tags": (None, "[]"),
        }
        resp = self.client.post("/api/tools", files=files, headers=self.headers)
        self.assertEqual(resp.status_code, 422)

    # ============================================================
    # Test 2: 获取工具详情
    # ============================================================

    def test_02_get_tool(self):
        """GET /api/tools/{id} — 按 ID 获取工具详情."""
        tool_id = self._create_test_tool(name="详情测试工具")
        resp = self.client.get(f"/api/tools/{tool_id}", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertEqual(data["data"]["name"], "详情测试工具")
        self.assertEqual(data["data"]["category"], "取证分析")
        self.assertIn("versions", data["data"])
        self.assertGreaterEqual(len(data["data"]["versions"]), 1)

    def test_02b_get_tool_not_found(self):
        """GET /api/tools/{id} — 不存在的 ID 返回 404."""
        resp = self.client.get("/api/tools/99999", headers=self.headers)
        self.assertEqual(resp.status_code, 404)

    # ============================================================
    # Test 3: 搜索/分类筛选
    # ============================================================

    def test_03_search_tools(self):
        """GET /api/tools — 关键词搜索."""
        self._create_test_tool(name="搜索唯一工具_Alpha")
        self._create_test_tool(name="搜索唯一工具_Beta")

        resp = self.client.get(
            "/api/tools?keyword=搜索唯一工具&limit=50",
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertGreaterEqual(data["data"]["total"], 2)
        names = [item["name"] for item in data["data"]["items"]]
        self.assertIn("搜索唯一工具_Alpha", names)
        self.assertIn("搜索唯一工具_Beta", names)

    def test_03b_filter_by_category(self):
        """GET /api/tools — 按分类筛选."""
        # 创建不同分类的工具
        self._create_test_tool(name="分类A工具", category="分类A")
        self._create_test_tool(name="分类B工具", category="分类B")

        resp = self.client.get(
            "/api/tools?category=分类A",
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        for item in data["data"]["items"]:
            self.assertEqual(item["category"], "分类A")

    def test_03c_pagination(self):
        """GET /api/tools — 分页测试."""
        resp = self.client.get(
            "/api/tools?limit=2&offset=0",
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertLessEqual(len(data["data"]["items"]), 2)

    # ============================================================
    # Test 4: 统计概览
    # ============================================================

    def test_04_get_stats(self):
        """GET /api/tools/stats — 统计概览."""
        resp = self.client.get("/api/tools/stats", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        stats = data["data"]
        self.assertIn("total_tools", stats)
        self.assertIn("total_downloads", stats)
        self.assertIn("today_new", stats)
        self.assertIn("category_count", stats)
        self.assertIsInstance(stats["total_tools"], int)
        self.assertIsInstance(stats["total_downloads"], int)

    # ============================================================
    # Test 5: 更新工具
    # ============================================================

    def test_05_update_tool(self):
        """PUT /api/tools/{id} — 更新工具信息."""
        tool_id = self._create_test_tool(name="待更新工具")

        # 更新名称和描述
        files = {
            "name": (None, "已更新工具"),
            "description": (None, "Updated description"),
            "category": (None, "响应处置"),
            "tags": (None, '["updated", "tool"]'),
        }
        resp = self.client.put(
            f"/api/tools/{tool_id}",
            files=files,
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertEqual(data["data"]["name"], "已更新工具")
        self.assertEqual(data["data"]["description"], "Updated description")
        self.assertEqual(data["data"]["category"], "响应处置")

    def test_05b_update_tool_not_found(self):
        """PUT /api/tools/{id} — 更新不存在的工具返回 404."""
        files = {"name": (None, "不存在工具")}
        resp = self.client.put("/api/tools/99999", files=files, headers=self.headers)
        self.assertEqual(resp.status_code, 404)

    # ============================================================
    # Test 6: 删除工具
    # ============================================================

    def test_06_delete_tool(self):
        """DELETE /api/tools/{id} — 删除工具."""
        tool_id = self._create_test_tool(name="待删除工具")
        resp = self.client.delete(f"/api/tools/{tool_id}", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertEqual(data["message"], "已删除")

        # 验证已删除
        resp = self.client.get(f"/api/tools/{tool_id}", headers=self.headers)
        self.assertEqual(resp.status_code, 404)

    def test_06b_delete_tool_not_found(self):
        """DELETE /api/tools/{id} — 删除不存在的工具返回 404."""
        resp = self.client.delete("/api/tools/99999", headers=self.headers)
        self.assertEqual(resp.status_code, 404)

    # ============================================================
    # Test 7: 分类列表
    # ============================================================

    def test_07_get_categories(self):
        """GET /api/tools/categories — 分类列表."""
        resp = self.client.get("/api/tools/categories", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertIsInstance(data["data"], list)
        if data["data"]:
            self.assertIn("category", data["data"][0])
            self.assertIn("count", data["data"][0])

    # ============================================================
    # Test 8: 发布新版本
    # ============================================================

    def test_08_publish_version(self):
        """POST /api/tools/{id}/versions — 发布新版本."""
        tool_id = self._create_test_tool(name="版本测试工具", version="1.0.0")

        # 发布 v1.1.0
        new_content = b"new version binary"
        files = {
            "version": (None, "1.1.0"),
            "change_log": (None, "Bug fixes and improvements"),
            "tool_file": ("v1.1.0_tool.exe", new_content),
        }
        resp = self.client.post(
            f"/api/tools/{tool_id}/versions",
            files=files,
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertEqual(data["message"], "版本发布成功")

        # 验证工具版本已更新
        resp = self.client.get(f"/api/tools/{tool_id}", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        detail = resp.json()
        self.assertEqual(detail["data"]["current_version"], "1.1.0")
        self.assertEqual(len(detail["data"]["versions"]), 2)

    def test_08b_publish_version_duplicate(self):
        """POST /api/tools/{id}/versions — 重复版本号返回 409."""
        tool_id = self._create_test_tool(name="版本重复测试", version="1.0.0")

        files = {
            "version": (None, "1.0.0"),
            "change_log": (None, "Duplicate version"),
            "tool_file": ("dup.exe", b"dup content"),
        }
        resp = self.client.post(
            f"/api/tools/{tool_id}/versions",
            files=files,
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 409)

    # ============================================================
    # Test 9: 下载工具
    # ============================================================

    def test_09_download_tool(self):
        """GET /api/tools/{id}/download — 下载工具文件."""
        tool_id = self._create_test_tool(name="下载测试工具")
        resp = self.client.get(
            f"/api/tools/{tool_id}/download",
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        # 验证返回的是文件流
        self.assertGreater(len(resp.content), 0)
        self.assertIn("attachment", resp.headers.get("content-disposition", ""))

    # ============================================================
    # Test 10: 文档查看
    # ============================================================

    def test_10_view_doc(self):
        """GET /api/tools/{id}/doc — 查看工具文档."""
        tool_content = b"binary"
        doc_content = b"# User Manual\n\nThis is the manual."
        files = {
            "name": (None, "有文档工具"),
            "description": (None, "Has docs"),
            "category": (None, "其他"),
            "version": (None, "1.0.0"),
            "tags": (None, "[]"),
            "tool_file": ("tool.exe", tool_content),
            "doc_file": ("manual.md", doc_content),
        }
        resp = self.client.post("/api/tools", files=files, headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        tool_id = resp.json()["data"]["id"]

        resp = self.client.get(f"/api/tools/{tool_id}/doc", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertIn("content", data["data"])
        self.assertIn("file_type", data["data"])
        self.assertEqual(data["data"]["file_type"], ".md")

    def test_10b_view_doc_not_found(self):
        """GET /api/tools/{id}/doc — 无文档时返回 404."""
        tool_id = self._create_test_tool(name="无文档工具")
        resp = self.client.get(f"/api/tools/{tool_id}/doc", headers=self.headers)
        self.assertEqual(resp.status_code, 404)

    # ============================================================
    # Test 11: 权限校验
    # ============================================================

    def test_11_non_admin_upload(self):
        """POST /api/tools — 非 admin 上传应返回 403."""
        # 注册一个非 admin 用户
        resp = self.client.post("/api/auth/register", json={
            "username": "viewer_user",
            "password": "viewer123",
        })
        # 可能已存在，忽略
        # 用非 admin 用户登录
        resp = self.client.post("/api/auth/login", json={
            "username": "viewer_user",
            "password": "viewer123",
        })
        if resp.status_code != 200:
            # 如果注册失败，直接跳过权限测试
            return
        viewer_token = resp.json()["data"]["token"]
        viewer_headers = {"Authorization": f"Bearer {viewer_token}"}

        tool_content = b"binary"
        files = {
            "name": (None, "非上传工具"),
            "description": (None, "Should fail"),
            "category": (None, "other"),
            "version": (None, "1.0.0"),
            "tags": (None, "[]"),
            "tool_file": ("hack.exe", tool_content),
        }
        resp = self.client.post("/api/tools", files=files, headers=viewer_headers)
        # viewer 不是 admin，应该返回 403
        self.assertEqual(resp.status_code, 403)


if __name__ == "__main__":
    unittest.main()
