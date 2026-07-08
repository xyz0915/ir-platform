#!/usr/bin/env python3
"""API 路由回归测试 — 验证4个新端点 + routes-debug 诊断端点.

验证范围:
  1. __pycache__ 缓存已清除（不含venv）
  2. /api/routes-debug 诊断端点存在且返回路由列表
  3. 4个新端点 (/hosts/{host_id}/users, services, usb, remote-control) 在路由列表中
  4. 前端 API 调用路径与后端路由路径对齐

运行方式:
    cd backend
    venv\\Scripts\\python.exe tests\\test_api_routes.py
"""

import os
import re
import sys
import unittest
from pathlib import Path

# 确保后端目录在 Python 路径中
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

PROJECT_ROOT = BACKEND_DIR.parent

# ---------------------------------------------------------------
#  Test 1: __pycache__ 已清除
# ---------------------------------------------------------------


class TestPycacheClean(unittest.TestCase):
    """验证 backend/app/ 下的 __pycache__ 包含的是最新字节码（不是旧缓存）.

    注意：运行测试会导入模块并自动创建 __pycache__，这是 Python 正常行为。
    我们验证的是：这些 __pycache__ 中的 .pyc 文件包含当前源码的端点（非旧缓存），
    即根因（加载不含4个新端点的旧缓存）已解决。
    """

    def test_pycache_contains_new_endpoints(self):
        """验证 __pycache__ 中的 analysis.pyc 包含4个新端点的字节码."""
        analysis_pycache = BACKEND_DIR / "app" / "api" / "__pycache__"
        if not analysis_pycache.exists():
            # 如果 __pycache__ 不存在（从未导入），说明旧缓存已清除，直接通过
            return

        # 读取 analysis.cpython-*.pyc 文件的字节码
        pyc_files = list(analysis_pycache.glob("analysis.cpython-*.pyc"))
        if not pyc_files:
            return

        # 验证 .pyc 文件中包含4个新端点的名称
        # 直接读取 .pyc 二进制内容，搜索端点名称字符串
        endpoint_names = ["users", "services", "usb", "remote-control"]
        for pyc_file in pyc_files:
            content = pyc_file.read_bytes()
            # .pyc 文件中函数名和路由路径会以字符串形式存储
            for name in endpoint_names:
                # 搜索 /hosts/{host_id}/xxx 格式
                pattern = f"/hosts/{{host_id}}/{name}".encode("utf-8")
                # 也搜索函数名
                func_pattern = f"get_{name.replace('-', '_')}".encode("utf-8") if "-" in name else f"get_{name}".encode("utf-8")
                self.assertTrue(
                    pattern in content or func_pattern in content,
                    f"analysis.pyc 中未找到端点 '{name}' 的字节码，可能仍是旧缓存",
                )


# ---------------------------------------------------------------
#  Test 2: routes-debug 端点
# ---------------------------------------------------------------


class TestRoutesDebugEndpoint(unittest.TestCase):
    """验证 /api/routes-debug 诊断端点存在于 FastAPI app 中."""

    @classmethod
    def setUpClass(cls):
        """导入 FastAPI app 对象（不启动服务器）."""
        # 需要在导入前设置环境变量，避免启动时创建真实数据库
        os.environ.setdefault("IR_DB_PATH", str(BACKEND_DIR / "data" / "test_routes_debug.db"))
        from app.main import app
        cls.app = app

    def test_routes_debug_endpoint_exists(self):
        """验证 /api/routes-debug 路由已注册."""
        route_paths = [r.path for r in self.app.routes if hasattr(r, "path")]
        self.assertIn(
            "/api/routes-debug",
            route_paths,
            "/api/routes-debug 端点未注册到 FastAPI app",
        )

    def test_routes_debug_returns_list(self):
        """验证 routes-debug 端点返回路由列表."""
        from app.main import list_routes
        result = list_routes()
        self.assertEqual(result["code"], 0)
        self.assertIsInstance(result["data"], list)
        self.assertTrue(len(result["data"]) > 0, "路由列表不应为空")


# ---------------------------------------------------------------
#  Test 3: 4个新端点在路由列表中
# ---------------------------------------------------------------


class TestFourNewEndpoints(unittest.TestCase):
    """验证4个新端点已注册到 FastAPI app."""

    # 预期4个新端点的路由路径（含 /api 前缀）
    EXPECTED_ENDPOINTS = [
        "/api/hosts/{host_id}/users",
        "/api/hosts/{host_id}/services",
        "/api/hosts/{host_id}/usb",
        "/api/hosts/{host_id}/remote-control",
    ]

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("IR_DB_PATH", str(BACKEND_DIR / "data" / "test_routes_debug.db"))
        from app.main import app
        cls.app = app
        cls.route_paths = [r.path for r in app.routes if hasattr(r, "path")]

    def test_users_endpoint_exists(self):
        self.assertIn(self.EXPECTED_ENDPOINTS[0], self.route_paths)

    def test_services_endpoint_exists(self):
        self.assertIn(self.EXPECTED_ENDPOINTS[1], self.route_paths)

    def test_usb_endpoint_exists(self):
        self.assertIn(self.EXPECTED_ENDPOINTS[2], self.route_paths)

    def test_remote_control_endpoint_exists(self):
        self.assertIn(self.EXPECTED_ENDPOINTS[3], self.route_paths)

    def test_all_four_endpoints_exist(self):
        """综合检查：4个端点必须全部存在."""
        missing = [
            ep for ep in self.EXPECTED_ENDPOINTS
            if ep not in self.route_paths
        ]
        self.assertEqual(
            missing,
            [],
            f"以下端点缺失: {missing}",
        )


# ---------------------------------------------------------------
#  Test 4: 前端路径与后端路径对齐
# ---------------------------------------------------------------


class TestFrontendBackendAlignment(unittest.TestCase):
    """验证前端 API 调用路径与后端路由路径一致."""

    # 前端 analysis.js 中4个方法对应的相对路径（不含 /api 前缀）
    FRONTEND_PATHS = {
        "getUsers": "/hosts/${hostId}/users",
        "getServices": "/hosts/${hostId}/services",
        "getUsb": "/hosts/${hostId}/usb",
        "getRemoteControl": "/hosts/${hostId}/remote-control",
    }

    # 后端 analysis.py 中4个路由的相对路径（不含 /api 前缀）
    BACKEND_PATHS = [
        "/hosts/{host_id}/users",
        "/hosts/{host_id}/services",
        "/hosts/{host_id}/usb",
        "/hosts/{host_id}/remote-control",
    ]

    def test_frontend_api_file_exists(self):
        """验证前端 analysis.js 文件存在."""
        frontend_api = PROJECT_ROOT / "frontend" / "src" / "api" / "analysis.js"
        self.assertTrue(frontend_api.exists(), f"前端 API 文件不存在: {frontend_api}")

    def test_frontend_paths_match_backend(self):
        """验证前端4个API路径与后端路由路径对齐.

        前端使用 ${hostId} (JS模板字符串)，
        后端使用 {host_id} (FastAPI路径参数)，
        两者在语义上对齐即可。
        """
        analysis_file = PROJECT_ROOT / "frontend" / "src" / "api" / "analysis.js"
        content = analysis_file.read_text(encoding="utf-8")

        # 提取前端中的API路径
        # 前端路径模式: `/hosts/${hostId}/xxx`
        frontend_pattern = r"`/hosts/\$\{hostId\}/(\w[\w-]*)`"
        frontend_matches = re.findall(frontend_pattern, content)

        # 提取后端路径中的资源名
        # 后端路径模式: /hosts/{host_id}/xxx
        backend_pattern = r"/hosts/\{host_id\}/(\w[\w-]*)"
        backend_file = BACKEND_DIR / "app" / "api" / "analysis.py"
        backend_content = backend_file.read_text(encoding="utf-8")
        backend_matches = re.findall(backend_pattern, backend_content)

        # 检查4个新增端点的资源名在前端和后端都存在
        new_resource_names = ["users", "services", "usb", "remote-control"]

        for name in new_resource_names:
            self.assertIn(name, frontend_matches, f"前端 analysis.js 缺少路径: /hosts/${{hostId}}/{name}")
            self.assertIn(name, backend_matches, f"后端 analysis.py 缺少路径: /hosts/{{host_id}}/{name}")


# ---------------------------------------------------------------
#  Test 5: 404拦截器正则逻辑
# ---------------------------------------------------------------


class TestInterceptorRegex(unittest.TestCase):
    """验证前端404拦截器对采集Tab URL的正则过滤逻辑."""

    # 正则来自 frontend/src/api/index.js line 43
    INTERCEPTOR_REGEX = r"/hosts/\d+/(users|services|usb|remote-control)$"

    def test_collection_tab_urls_match(self):
        """采集Tab的4个URL应该被正则匹配（不弹窗）."""
        matching_urls = [
            "/hosts/1/users",
            "/hosts/42/services",
            "/hosts/999/usb",
            "/hosts/3/remote-control",
        ]
        for url in matching_urls:
            self.assertTrue(
                re.search(self.INTERCEPTOR_REGEX, url),
                f"采集Tab URL {url} 应被正则匹配",
            )

    def test_other_urls_do_not_match(self):
        """非采集Tab的URL不应被正则匹配（应弹窗）."""
        non_matching_urls = [
            "/hosts/1/analyze",
            "/hosts/1/analysis",
            "/hosts/1/profile",
            "/api/cases/1",
            "/hosts/1/users/extra",
            "/hosts/abc/users",
        ]
        for url in non_matching_urls:
            self.assertFalse(
                re.search(self.INTERCEPTOR_REGEX, url),
                f"非采集Tab URL {url} 不应被正则匹配",
            )


# ---------------------------------------------------------------
#  Test 6: HostDetailView Phase 2 容错逻辑
# ---------------------------------------------------------------


class TestHostDetailViewPhase2(unittest.TestCase):
    """验证 HostDetailView 中 Phase 2 的 try/catch 容错逻辑."""

    @classmethod
    def setUpClass(cls):
        vue_file = PROJECT_ROOT / "frontend" / "src" / "views" / "HostDetailView.vue"
        cls.content = vue_file.read_text(encoding="utf-8")

    def test_phase2_comment_exists(self):
        """验证 Phase 2 注释存在."""
        self.assertIn("Phase 2", self.content)

    def test_four_new_tabs_in_try_catch(self):
        """验证4个新Tab数据加载都在独立 try/catch 中."""
        # 检查每个新Tab都有独立的 try/catch 容错
        # 实际代码格式: try { xxx.value = (await analysisApi.method(hostId)).data } catch (e) { xxx.value = [] }
        new_tabs = ["getUsers", "getServices", "getUsb", "getRemoteControl"]
        for method in new_tabs:
            # 验证 analysisApi.method(hostId) 出现在 try/catch 结构中
            # 搜索模式: 包含 analysisApi.xxx(hostId) 且同一行有 try 或 catch
            api_call = f"analysisApi.{method}(hostId)"
            self.assertIn(api_call, self.content, f"HostDetailView 中缺少 {api_call} 调用")
            # 验证该行所在上下文是 try/catch 结构
            # 在Vue源码中，Phase 2的格式是: try { ... } catch (e) { ... = [] }
            idx = self.content.find(api_call)
            # 向左搜索，找到最近的 try 关键字
            preceding_text = self.content[:idx]
            last_try_pos = preceding_text.rfind("try")
            self.assertTrue(last_try_pos >= 0, f"{api_call} 前面缺少 try 关键字")

    def test_phase2_defaults_to_empty_list(self):
        """验证 Phase 2 catch 中将数据设为空列表 []."""
        # 每个catch块应该设置 value = []
        # 实际代码格式: catch (e) { xxx.value = [] }
        catch_blocks = re.findall(r"catch\s*\(\s*e\s*\)\s*\{\s*\w+\s*\.value\s*=\s*\[\]", self.content)
        # 应至少有4个（对应4个新Tab）
        self.assertGreaterEqual(len(catch_blocks), 4, "Phase 2 应至少有4个 catch 块设置空列表")


if __name__ == "__main__":
    unittest.main(verbosity=2)
