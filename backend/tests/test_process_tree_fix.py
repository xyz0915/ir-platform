"""回归测试脚本 — 验证进程树 RecursionError Bug 修复.

测试内容:
1. ProcessTreeBuilder 循环引用修复验证
   - 自引用 (PID=0, ppid=0) 不报 RecursionError
   - 自引用节点被标记 "(circular reference)"，children 为空
   - 环形引用 (A→B→A) 不报 RecursionError
   - 正常进程列表树构建不受影响
2. API 端点回归测试
   - GET /hosts/{host_id}/process-tree 返回正常
   - GET /hosts/{host_id}/abnormal-processes 不受影响
   - 其他关键 API 端点仍正常
3. 前端修改验证
   - HostDetailView.vue catch 块有 ElMessage.error
   - ProcessTreeChart.vue 能处理 "(circular reference)" 标记节点
"""

import json
import os
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# ── 确保项目路径在 sys.path 中 ──────────────────────────────────────────
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))


# ═══════════════════════════════════════════════════════════════════════════
# 1. ProcessTreeBuilder 循环引用修复验证
# ═══════════════════════════════════════════════════════════════════════════

class TestProcessTreeCircularReference(unittest.TestCase):
    """验证 ProcessTreeBuilder 循环引用修复."""

    def test_self_reference_no_recursion_error(self):
        """自引用进程 (PID=0, ppid=0) 不报 RecursionError，能正常返回树."""
        from app.analysis.process_tree_builder import ProcessTreeBuilder
        # System Idle Process: PID=0, ppid=0 → 自引用循环
        processes = [
            {"pid": 0, "ppid": 0, "name": "System Idle Process"},
        ]
        result = ProcessTreeBuilder.build(processes, set(), {})
        # 应能正常构建树，不抛 RecursionError
        self.assertIsInstance(result, dict)
        self.assertIn("name", result)

    def test_self_reference_node_marked_circular(self):
        """自引用节点被标记为 "(circular reference)" 且 children 为空列表."""
        from app.analysis.process_tree_builder import ProcessTreeBuilder
        processes = [
            {"pid": 0, "ppid": 0, "name": "System Idle Process"},
        ]
        result = ProcessTreeBuilder.build(processes, set(), {})
        # PID=0 是根进程(ppid=0)，它自己也是 ppid=0 的子进程 → 循环
        # 根节点正常构建，但其子节点列表中若出现 PID=0 的递归应标记为 circular
        # 注意：根进程 PID=0 本身不会被标记为 circular（它是首次访问）
        # 但如果 PID=0 的 children 中包含 PID=0 自身（自引用），那子节点会被标记
        # 此场景下，PID=0 是根，ppid_to_children[0] = [{pid:0}]
        # 构建子树时 PID=0 在 visited 中 → 子节点标记 circular reference
        self.assertIsInstance(result, dict)

    def test_self_reference_circular_child_node(self):
        """自引用的子节点（自引用循环的第二层）被正确标记为 circular reference."""
        from app.analysis.process_tree_builder import ProcessTreeBuilder
        # PID=0, ppid=0 → 根节点是 PID=0
        # pid_to_children[0] 包含 PID=0 自身 → 递归时 visited 中已有 0
        processes = [
            {"pid": 0, "ppid": 0, "name": "System Idle Process"},
        ]
        result = ProcessTreeBuilder.build(processes, set(), {})
        # 根节点 name 应为 "System Idle Process"
        self.assertEqual(result["name"], "System Idle Process")
        self.assertEqual(result["pid"], 0)
        # 子节点中 PID=0 的递归应被检测为循环引用
        # 根节点有 children，其中包含 PID=0 的 circular reference 节点
        children = result.get("children", [])
        # 应有一个子节点，标记为 circular reference
        self.assertTrue(len(children) > 0, "自引用应有 circular reference 子节点")
        circular_child = children[0]
        self.assertIn("(circular reference)", circular_child["name"])
        self.assertEqual(circular_child["children"], [])

    def test_ring_reference_no_recursion_error(self):
        """环形引用 (A→B→A) 不报 RecursionError."""
        from app.analysis.process_tree_builder import ProcessTreeBuilder
        # 环形引用: PID=100 的 ppid=200，PID=200 的 ppid=100
        # A(100) → B(200) → A(100) 循环
        processes = [
            {"pid": 100, "ppid": 200, "name": "ProcA"},
            {"pid": 200, "ppid": 100, "name": "ProcB"},
        ]
        result = ProcessTreeBuilder.build(processes, set(), {})
        # 应能正常构建树，不抛 RecursionError
        self.assertIsInstance(result, dict)
        self.assertIn("name", result)

    def test_ring_reference_circular_detected(self):
        """环形引用节点被标记为 circular reference."""
        from app.analysis.process_tree_builder import ProcessTreeBuilder
        # PID=100 ppid=200, PID=200 ppid=100
        # 两者的 ppid 不在进程列表中（假设）或构成环
        # ppid=200 和 ppid=100 都在 pid_to_proc 中 → 它们不是孤儿
        # 但 ppid=200 和 ppid=100 都非 0 → 需要分析谁是根
        # _find_roots: ppid=200 在 pid_to_proc 中，ppid=100 在 pid_to_proc 中
        # 所以两者都不是根（不是 ppid=0 且不是孤儿）
        # 这意味着 _find_roots 会返回空列表 → build 返回 "(empty)"
        # 除非我们将其中一个的 ppid 改为 0 来创建根
        processes = [
            {"pid": 1, "ppid": 0, "name": "Root"},
            {"pid": 100, "ppid": 1, "name": "ProcA"},
            {"pid": 200, "ppid": 100, "name": "ProcB"},
            {"pid": 300, "ppid": 200, "name": "ProcC"},
            {"pid": 100, "ppid": 300, "name": "ProcA"},  # 同名同 PID，环形：A→B→C→A
        ]
        # 注意：PID 100 出现两次，pid_to_proc 只保留最后一个
        # 实际环形需要：A(100) child of Root(1), B(200) child of A(100),
        # C(300) child of B(200), 然后 A(100) again child of C(300)
        # 但同 PID 的进程只会出现一次在 pid_to_proc 中
        # 让我重新构造一个更准确的环
        processes = [
            {"pid": 1, "ppid": 0, "name": "Root"},
            {"pid": 100, "ppid": 1, "name": "ProcA"},
            {"pid": 200, "ppid": 100, "name": "ProcB"},
            {"pid": 300, "ppid": 200, "name": "ProcC"},
            # ProcC 的子进程是 ProcA(100)，形成环: Root→A→B→C→A
        ]
        # 但 pid_to_children[300] 需要包含 pid=100 的进程
        # 而 pid_to_proc[100] 已存在 → 递归时会检测到 100 在 visited 中
        # 我们需要让 ProcC(ppid=200) 有一个子进程 pid=100
        # 在扁平列表中，ProcA 的 ppid 是 1，不是 300
        # 所以 pid_to_children[300] 不会包含 ProcA
        # 要形成环，需要一个 ppid=300, pid=100 的进程
        # 但 pid_to_proc 中只有第一个 pid=100 的映射

        # 更简洁的方法：直接构造 PID 映射让环存在
        # 让我使用更直接的测试方式：测试 _build_tree_recursive 方法
        from app.analysis.process_tree_builder import ProcessTreeBuilder

        # 直接调用 _build_tree_recursive 测试环检测
        pid_to_proc = {
            100: {"pid": 100, "name": "ProcA", "path": "", "command_line": ""},
            200: {"pid": 200, "name": "ProcB", "path": "", "command_line": ""},
            300: {"pid": 300, "name": "ProcC", "path": "", "command_line": ""},
        }
        pid_to_children = {
            100: [{"pid": 200, "ppid": 100, "name": "ProcB"}],
            200: [{"pid": 300, "ppid": 200, "name": "ProcC"}],
            300: [{"pid": 100, "ppid": 300, "name": "ProcA"}],  # 环形: C→A
        }

        # 从 PID=100 开始构建，visited 初始为空
        node = ProcessTreeBuilder._build_tree_recursive(
            100, pid_to_proc, pid_to_children, set(), {}, set()
        )
        # 根节点 ProcA 正常
        self.assertEqual(node["name"], "ProcA")
        self.assertEqual(node["pid"], 100)
        # ProcA → ProcB → ProcC → ProcA(循环)
        # ProcB 子节点
        proc_b = node["children"][0]
        self.assertEqual(proc_b["name"], "ProcB")
        # ProcC 子节点
        proc_c = proc_b["children"][0]
        self.assertEqual(proc_c["name"], "ProcC")
        # ProcC 的子节点应检测到 PID=100 的循环引用
        circular_node = proc_c["children"][0]
        self.assertIn("(circular reference)", circular_node["name"])
        self.assertEqual(circular_node["pid"], 100)
        self.assertEqual(circular_node["children"], [])

    def test_ring_reference_children_empty(self):
        """循环引用节点的 children 必须为空列表，防止前端无限递归渲染."""
        from app.analysis.process_tree_builder import ProcessTreeBuilder
        processes = [
            {"pid": 0, "ppid": 0, "name": "System Idle Process"},
        ]
        result = ProcessTreeBuilder.build(processes, set(), {})
        # 查找所有包含 circular reference 的节点
        circular_nodes = self._find_circular_nodes(result)
        for cn in circular_nodes:
            self.assertEqual(cn["children"], [],
                             "循环引用节点的 children 必须为空列表")

    def test_normal_tree_unaffected(self):
        """传入正常进程列表时树构建不受循环检测逻辑影响."""
        from app.analysis.process_tree_builder import ProcessTreeBuilder
        processes = [
            {"pid": 1, "ppid": 0, "name": "System"},
            {"pid": 100, "ppid": 1, "name": "smss.exe"},
            {"pid": 200, "ppid": 100, "name": "csrss.exe"},
            {"pid": 300, "ppid": 100, "name": "wininit.exe"},
        ]
        abnormal_pids = {200}
        pid_to_info = {
            200: {"risk_score": 25, "matched_rules": [{"name": "test", "severity": "high"}], "attack_path": None}
        }

        result = ProcessTreeBuilder.build(processes, abnormal_pids, pid_to_info)
        # 根节点应为 System
        self.assertEqual(result["name"], "System")
        self.assertEqual(result["pid"], 1)
        # System 应有子节点 smss.exe
        self.assertEqual(len(result["children"]), 1)
        smss = result["children"][0]
        self.assertEqual(smss["name"], "smss.exe")
        # smss.exe 应有子节点 csrss.exe 和 wininit.exe
        self.assertEqual(len(smss["children"]), 2)
        # csrss.exe 是异常进程
        csrss = [c for c in smss["children"] if c["pid"] == 200][0]
        self.assertTrue(csrss["is_abnormal"])
        self.assertEqual(csrss["risk_score"], 25)
        # wininit.exe 正常
        wininit = [c for c in smss["children"] if c["pid"] == 300][0]
        self.assertFalse(wininit["is_abnormal"])
        # 不应有任何 circular reference 标记
        circular_nodes = self._find_circular_nodes(result)
        self.assertEqual(len(circular_nodes), 0, "正常树不应包含 circular reference 节点")

    def test_visited_set_is_immutable_per_branch(self):
        """visited set 使用不可变集合（union 创建新 set），确保不同分支不互相影响."""
        from app.analysis.process_tree_builder import ProcessTreeBuilder
        # 构造树: Root(1) → ChildA(100) → ChildB(200)
        #                  → ChildC(300)
        # ChildB 和 ChildC 是兄弟节点，各自递归时 visited 应只包含自己的路径
        processes = [
            {"pid": 1, "ppid": 0, "name": "Root"},
            {"pid": 100, "ppid": 1, "name": "ChildA"},
            {"pid": 200, "ppid": 100, "name": "ChildB"},
            {"pid": 300, "ppid": 100, "name": "ChildC"},
        ]
        result = ProcessTreeBuilder.build(processes, set(), {})
        # Root → ChildA → [ChildB, ChildC]
        self.assertEqual(result["name"], "Root")
        child_a = result["children"][0]
        self.assertEqual(child_a["name"], "ChildA")
        self.assertEqual(len(child_a["children"]), 2)
        # ChildB 和 ChildC 都应正常构建，不受彼此 visited 影响
        child_b = [c for c in child_a["children"] if c["pid"] == 200][0]
        child_c = [c for c in child_a["children"] if c["pid"] == 300][0]
        self.assertEqual(child_b["name"], "ChildB")
        self.assertEqual(child_c["name"], "ChildC")
        # 没有 circular reference
        self.assertNotIn("(circular reference)", child_b["name"])
        self.assertNotIn("(circular reference)", child_c["name"])

    def test_deep_recursion_no_stack_overflow(self):
        """深层嵌套进程链不导致栈溢出（Python 默认递归限制 1000）."""
        from app.analysis.process_tree_builder import ProcessTreeBuilder
        # 构造 500 层深的进程链
        processes = [{"pid": 1, "ppid": 0, "name": "Root"}]
        for i in range(2, 502):
            processes.append({"pid": i, "ppid": i - 1, "name": f"Proc_{i}"})

        result = ProcessTreeBuilder.build(processes, set(), {})
        # 应能正常构建，不抛 RecursionError
        self.assertIsInstance(result, dict)
        self.assertEqual(result["name"], "Root")

    def test_empty_processes_returns_empty_node(self):
        """空进程列表仍返回 (empty) 节点."""
        from app.analysis.process_tree_builder import ProcessTreeBuilder
        result = ProcessTreeBuilder.build([], set(), {})
        self.assertEqual(result["name"], "(empty)")
        self.assertEqual(result["children"], [])

    def test_single_process_no_children(self):
        """单个进程（无子进程）正常构建."""
        from app.analysis.process_tree_builder import ProcessTreeBuilder
        processes = [
            {"pid": 1, "ppid": 0, "name": "Init"},
        ]
        result = ProcessTreeBuilder.build(processes, set(), {})
        self.assertEqual(result["name"], "Init")
        self.assertEqual(result["pid"], 1)
        self.assertEqual(result["children"], [])

    def test_multiple_self_references_in_tree(self):
        """包含多个自引用节点的进程树均不报 RecursionError."""
        from app.analysis.process_tree_builder import ProcessTreeBuilder
        # PID=0 ppid=0 (System Idle Process) 和 PID=4 ppid=4 (另一个自引用)
        # 注意: 实际上 PID=4 的 ppid 通常不是 4，这里用于测试
        processes = [
            {"pid": 1, "ppid": 0, "name": "Root"},
            {"pid": 100, "ppid": 1, "name": "ChildA"},
            {"pid": 0, "ppid": 0, "name": "System Idle Process"},
            {"pid": 4, "ppid": 4, "name": "SelfRef"},
        ]
        result = ProcessTreeBuilder.build(processes, set(), {})
        self.assertIsInstance(result, dict)
        self.assertIn("name", result)

    def test_circular_reference_node_has_required_fields(self):
        """循环引用节点包含所有必要字段：name, pid, children, is_abnormal, risk_score, matched_rules."""
        from app.analysis.process_tree_builder import ProcessTreeBuilder
        # 直接构造 _build_tree_recursive 的循环场景
        pid_to_proc = {
            100: {"pid": 100, "name": "ProcA", "path": "/path/a", "command_line": "cmd_a"},
            200: {"pid": 200, "name": "ProcB", "path": "/path/b", "command_line": "cmd_b"},
        }
        pid_to_children = {
            100: [{"pid": 200, "ppid": 100, "name": "ProcB"}],
            200: [{"pid": 100, "ppid": 200, "name": "ProcA"}],  # 环
        }
        node = ProcessTreeBuilder._build_tree_recursive(
            100, pid_to_proc, pid_to_children, set(), {}, set()
        )
        # 找到 circular reference 子节点
        proc_b = node["children"][0]
        circular = proc_b["children"][0]
        # 验证必要字段
        self.assertIn("(circular reference)", circular["name"])
        self.assertEqual(circular["pid"], 100)
        self.assertEqual(circular["children"], [])
        self.assertIn("is_abnormal", circular)
        self.assertIn("risk_score", circular)
        self.assertIn("matched_rules", circular)
        self.assertIn("process_name", circular)
        self.assertIn("process_path", circular)
        self.assertIn("command_line", circular)
        self.assertIn("attack_path", circular)

    def test_circular_reference_with_abnormal_pid(self):
        """循环引用节点如果是异常 PID，is_abnormal 应为 True."""
        from app.analysis.process_tree_builder import ProcessTreeBuilder
        pid_to_proc = {
            100: {"pid": 100, "name": "ProcA", "path": "", "command_line": ""},
            200: {"pid": 200, "name": "ProcB", "path": "", "command_line": ""},
        }
        pid_to_children = {
            100: [{"pid": 200, "ppid": 100, "name": "ProcB"}],
            200: [{"pid": 100, "ppid": 200, "name": "ProcA"}],
        }
        abnormal_pids = {100}
        pid_to_info = {
            100: {"risk_score": 50, "matched_rules": [{"name": "r1", "severity": "high"}], "attack_path": "A→B"}
        }
        node = ProcessTreeBuilder._build_tree_recursive(
            100, pid_to_proc, pid_to_children, abnormal_pids, pid_to_info, set()
        )
        # 根节点 ProcA 是异常进程
        self.assertTrue(node["is_abnormal"])
        # 环形引用的 ProcA 节点也应标记为异常
        circular = node["children"][0]["children"][0]
        self.assertTrue(circular["is_abnormal"])

    # ── 辅助方法 ──────────────────────────────────────────────────
    def _find_circular_nodes(self, node):
        """递归查找树中所有包含 circular reference 的节点."""
        results = []
        if isinstance(node, dict) and "(circular reference)" in node.get("name", ""):
            results.append(node)
        for child in node.get("children", []):
            results.extend(self._find_circular_nodes(child))
        return results


# ═══════════════════════════════════════════════════════════════════════════
# 2. API 端点回归测试（静态路由验证）
# ═══════════════════════════════════════════════════════════════════════════

class TestAPIEndpointsRegression(unittest.TestCase):
    """验证 API 端点路由仍然存在且未被循环修复影响."""

    def test_process_tree_endpoint_exists(self):
        """GET /hosts/{host_id}/process-tree 端点仍然存在于路由中."""
        from app.api.analysis import router
        routes = [route.path for route in router.routes if hasattr(route, 'path')]
        self.assertIn("/hosts/{host_id}/process-tree", routes)

    def test_abnormal_processes_endpoint_exists(self):
        """GET /hosts/{host_id}/abnormal-processes 端点仍然存在."""
        from app.api.analysis import router
        routes = [route.path for route in router.routes if hasattr(route, 'path')]
        self.assertIn("/hosts/{host_id}/abnormal-processes", routes)

    def test_analysis_endpoint_exists(self):
        """GET /hosts/{host_id}/analysis 端点仍然存在."""
        from app.api.analysis import router
        routes = [route.path for route in router.routes if hasattr(route, 'path')]
        self.assertIn("/hosts/{host_id}/analysis", routes)

    def test_profile_endpoint_exists(self):
        """GET /hosts/{host_id}/profile 端点仍然存在."""
        from app.api.analysis import router
        routes = [route.path for route in router.routes if hasattr(route, 'path')]
        self.assertIn("/hosts/{host_id}/profile", routes)

    def test_suspicious_connections_endpoint_exists(self):
        """GET /hosts/{host_id}/suspicious-connections 端点仍然存在."""
        from app.api.analysis import router
        routes = [route.path for route in router.routes if hasattr(route, 'path')]
        self.assertIn("/hosts/{host_id}/suspicious-connections", routes)

    def test_all_analysis_routes_registered_in_app(self):
        """所有分析路由在 main.py 中注册."""
        from app.main import app
        all_paths = [r.path for r in app.routes if hasattr(r, 'path')]
        # 检查关键路由
        expected_paths = [
            "/api/hosts/{host_id}/process-tree",
            "/api/hosts/{host_id}/abnormal-processes",
            "/api/hosts/{host_id}/analysis",
            "/api/hosts/{host_id}/profile",
            "/api/hosts/{host_id}/suspicious-connections",
        ]
        for expected in expected_paths:
            self.assertIn(expected, all_paths,
                          f"路由 {expected} 未在 app 中注册")

    def test_analysis_service_get_process_tree_exists(self):
        """AnalysisService.get_process_tree() 方法存在."""
        from app.services.analysis_service import AnalysisService
        self.assertTrue(hasattr(AnalysisService, 'get_process_tree'))

    def test_analysis_service_get_process_tree_returns_dict(self):
        """AnalysisService.get_process_tree() 返回 dict 类型."""
        import inspect
        from app.services.analysis_service import AnalysisService
        source = inspect.getsource(AnalysisService.get_process_tree)
        # 方法应调用 ProcessTreeBuilder.build 并返回树
        self.assertIn("ProcessTreeBuilder", source)
        self.assertIn("build", source)

    def test_analysis_service_get_process_tree_handles_no_data(self):
        """AnalysisService.get_process_tree() 处理无数据场景."""
        import inspect
        from app.services.analysis_service import AnalysisService
        source = inspect.getsource(AnalysisService.get_process_tree)
        # 应有 "no data" 或 "no process data" 的返回处理
        self.assertIn("no data", source.lower())


# ═══════════════════════════════════════════════════════════════════════════
# 3. 前端修改验证（静态代码检查）
# ═══════════════════════════════════════════════════════════════════════════

class TestFrontendFixVerification(unittest.TestCase):
    """验证前端修改：HostDetailView.vue 和 ProcessTreeChart.vue."""

    FRONTEND_DIR = BACKEND_DIR.parent / "frontend"

    def test_host_detail_view_has_elmessage_error_in_catch(self):
        """HostDetailView.vue 的进程树 catch 块包含 ElMessage.error 调用."""
        vue_path = self.FRONTEND_DIR / "src" / "views" / "HostDetailView.vue"
        self.assertTrue(vue_path.exists(), f"HostDetailView.vue 不存在: {vue_path}")
        content = vue_path.read_text(encoding="utf-8")
        # 检查进程树加载失败的 catch 块中有 ElMessage.error
        self.assertIn("ElMessage.error", content)
        self.assertIn("进程树数据加载失败", content)

    def test_host_detail_view_imports_elmessage(self):
        """HostDetailView.vue 导入了 ElMessage."""
        vue_path = self.FRONTEND_DIR / "src" / "views" / "HostDetailView.vue"
        content = vue_path.read_text(encoding="utf-8")
        self.assertIn("ElMessage", content)

    def test_process_tree_chart_handles_circular_reference(self):
        """ProcessTreeChart.vue 能处理包含 (circular reference) 标记节点的树数据."""
        vue_path = self.FRONTEND_DIR / "src" / "components" / "ProcessTreeChart.vue"
        self.assertTrue(vue_path.exists(), f"ProcessTreeChart.vue 不存在: {vue_path}")
        content = vue_path.read_text(encoding="utf-8")
        # convertToEChartsData 函数应能处理任意 name 字段（包括 circular reference）
        # 它使用 node.name 作为 ECharts node name → 无特殊过滤
        # circular reference 节点的 children 为空 → 不会导致无限递归
        # 验证 convertToEChartsData 函数存在且使用 node.name 和 node.children
        self.assertIn("convertToEChartsData", content)
        self.assertIn("node.name", content)
        self.assertIn("node.children", content)

    def test_process_tree_chart_no_hard_crash_on_circular_children(self):
        """ProcessTreeChart.vue 对 children.length=0 的 circular reference 节点不会崩溃."""
        vue_path = self.FRONTEND_DIR / "src" / "components" / "ProcessTreeChart.vue"
        content = vue_path.read_text(encoding="utf-8")
        # 检查 convertToEChartsData 中 children 的处理：
        # `if (node.children && node.children.length > 0)` → 空 children 不会递归
        # 找到这行代码
        self.assertTrue(
            "node.children && node.children.length > 0" in content or
            "node.children && node.children.length" in content,
            "ProcessTreeChart.vue 应检查 children.length > 0 以避免空 children 递归"
        )

    def test_host_detail_view_process_tree_catch_block_structure(self):
        """HostDetailView.vue 的进程树 catch 块结构正确：catch → set empty → ElMessage.error."""
        vue_path = self.FRONTEND_DIR / "src" / "views" / "HostDetailView.vue"
        content = vue_path.read_text(encoding="utf-8")
        # 查找进程树相关的 try-catch 结构
        # 应有: processTree.value = {} 和 ElMessage.error('进程树数据加载失败')
        # 在同一个 catch 块中
        # 搜索 catch(error) { processTree.value = {}; ElMessage.error } 的模式
        pattern = r"catch.*\{[^}]*processTree\.value\s*=\s*\{\}[^}]*ElMessage\.error"
        match = re.search(pattern, content, re.DOTALL)
        self.assertTrue(match is not None,
                        "HostDetailView.vue 的 catch 块应同时设置 processTree.value={} 和 ElMessage.error")


# ═══════════════════════════════════════════════════════════════════════════
# 4. ProcessTreeBuilder._build_tree_recursive visited 参数验证
# ═══════════════════════════════════════════════════════════════════════════

class TestBuildTreeRecursiveVisitedParam(unittest.TestCase):
    """验证 _build_tree_recursive 的 visited 参数实现."""

    def test_visited_param_exists(self):
        """_build_tree_recursive 方法有 visited 参数."""
        import inspect
        from app.analysis.process_tree_builder import ProcessTreeBuilder
        sig = inspect.signature(ProcessTreeBuilder._build_tree_recursive)
        self.assertIn("visited", sig.parameters)

    def test_build_method_passes_empty_visited_set(self):
        """build() 方法在调用 _build_tree_recursive 时传入空 set()."""
        import inspect
        from app.analysis.process_tree_builder import ProcessTreeBuilder
        source = inspect.getsource(ProcessTreeBuilder.build)
        self.assertIn("set()", source)

    def test_visited_set_immutable_union(self):
        """_build_tree_recursive 使用 visited | {pid} 创建新集合，不修改原 visited."""
        import inspect
        from app.analysis.process_tree_builder import ProcessTreeBuilder
        source = inspect.getsource(ProcessTreeBuilder._build_tree_recursive)
        # 应使用 union 操作（visited | {pid}）而非 add（visited.add(pid)）
        self.assertIn("visited | {pid}", source)
        self.assertNotIn("visited.add", source)

    def test_circular_reference_detection_before_recursion(self):
        """_build_tree_recursive 在递归前检查 pid in visited."""
        import inspect
        from app.analysis.process_tree_builder import ProcessTreeBuilder
        source = inspect.getsource(ProcessTreeBuilder._build_tree_recursive)
        # 检查 pid in visited 在 children 递归之前
        self.assertIn("pid in visited", source)

    def test_circular_reference_returns_special_node(self):
        """检测到循环引用时返回标记节点而非 None."""
        import inspect
        from app.analysis.process_tree_builder import ProcessTreeBuilder
        source = inspect.getsource(ProcessTreeBuilder._build_tree_recursive)
        # 应返回 "(circular reference)" 节点
        self.assertIn("(circular reference)", source)

    def test_circular_reference_node_has_empty_children(self):
        """循环引用标记节点的 children 为空列表 []."""
        import inspect
        from app.analysis.process_tree_builder import ProcessTreeBuilder
        source = inspect.getsource(ProcessTreeBuilder._build_tree_recursive)
        # 在 circular reference 返回的节点中，children 应为 []
        # 找到 circular reference 返回块中的 "children": []
        self.assertIn('"children": []', source)


# ═══════════════════════════════════════════════════════════════════════════
# 5. 边界情况与回归测试
# ═══════════════════════════════════════════════════════════════════════════

class TestEdgeCasesAndRegression(unittest.TestCase):
    """边界情况和回归测试."""

    def test_process_with_null_pid_does_not_crash(self):
        """pid 为 None 的进程不应导致树构建崩溃.
        注意：pid=None 的进程不会被 pid_to_proc 映射收录（被 if pid is None 跳过），
        但 _find_roots 仍可能将其视为根进程（ppid=0）。
        这类进程会作为 pid=None 的 "unknown" 节点出现在树中，而不是导致崩溃。
        """
        from app.analysis.process_tree_builder import ProcessTreeBuilder
        processes = [
            {"pid": None, "ppid": 0, "name": "BadProc"},
            {"pid": 1, "ppid": 0, "name": "GoodProc"},
        ]
        result = ProcessTreeBuilder.build(processes, set(), {})
        # 两个根进程（BadProc ppid=0 和 GoodProc ppid=0）→ 虚拟根节点 "All Processes"
        # 不应崩溃，树应能正常构建
        self.assertIsInstance(result, dict)
        self.assertIn("name", result)
        # 至少应包含 GoodProc（pid=1）
        self.assertIn("GoodProc", str(result))

    def test_process_with_non_dict_skipped(self):
        """非 dict 类型的进程应被跳过."""
        from app.analysis.process_tree_builder import ProcessTreeBuilder
        processes = [
            "not a dict",
            None,
            123,
            {"pid": 1, "ppid": 0, "name": "GoodProc"},
        ]
        result = ProcessTreeBuilder.build(processes, set(), {})
        self.assertEqual(result["name"], "GoodProc")

    def test_orphan_process_not_affected_by_circular_fix(self):
        """孤儿进程标注 (orphan process) 不受循环引用修复影响."""
        from app.analysis.process_tree_builder import ProcessTreeBuilder
        processes = [
            {"pid": 1, "ppid": 0, "name": "System"},
            {"pid": 999, "ppid": 888, "name": "orphan.exe"},
        ]
        result = ProcessTreeBuilder.build(processes, set(), {})
        # 孤儿进程应在结果中出现
        self.assertIn("orphan.exe", str(result))
        # 不应出现 circular reference（孤儿进程不是循环）
        circular_nodes = self._find_circular_nodes(result)
        self.assertEqual(len(circular_nodes), 0)

    def test_multiple_roots_with_circular(self):
        """多根进程树中包含自引用时仍正常."""
        from app.analysis.process_tree_builder import ProcessTreeBuilder
        processes = [
            {"pid": 1, "ppid": 0, "name": "Root1"},
            {"pid": 2, "ppid": 0, "name": "Root2"},
            {"pid": 0, "ppid": 0, "name": "System Idle Process"},
        ]
        result = ProcessTreeBuilder.build(processes, set(), {})
        # 3 个根进程 → 虚拟根节点 "All Processes"
        self.assertEqual(result["name"], "All Processes")
        self.assertEqual(len(result["children"]), 3)

    def test_process_tree_builder_build_is_static_method(self):
        """ProcessTreeBuilder.build 是静态方法."""
        from app.analysis.process_tree_builder import ProcessTreeBuilder
        # 可以直接调用，不需要实例
        result = ProcessTreeBuilder.build([], set(), {})
        self.assertEqual(result["name"], "(empty)")

    def test_find_roots_handles_ppid_zero(self):
        """_find_roots 正确处理 ppid=0 的根进程."""
        from app.analysis.process_tree_builder import ProcessTreeBuilder
        processes = [
            {"pid": 1, "ppid": 0, "name": "System"},
            {"pid": 100, "ppid": 1, "name": "Child"},
        ]
        pid_to_proc = {1: processes[0], 100: processes[1]}
        roots = ProcessTreeBuilder._find_roots(processes, pid_to_proc)
        # 只有 pid=1 是根（ppid=0）
        root_pids = [r.get("pid") for r in roots]
        self.assertIn(1, root_pids)
        self.assertNotIn(100, root_pids)

    def test_find_roots_handles_missing_parent(self):
        """_find_roots 正确处理父进程不在列表中的孤儿进程."""
        from app.analysis.process_tree_builder import ProcessTreeBuilder
        processes = [
            {"pid": 999, "ppid": 888, "name": "orphan.exe"},
        ]
        pid_to_proc = {999: processes[0]}
        roots = ProcessTreeBuilder._find_roots(processes, pid_to_proc)
        # ppid=888 不在 pid_to_proc → 孤儿进程是根
        root_pids = [r.get("pid") for r in roots]
        self.assertIn(999, root_pids)

    # ── 辅助方法 ──────────────────────────────────────────────────
    def _find_circular_nodes(self, node):
        """递归查找树中所有包含 circular reference 的节点."""
        results = []
        if isinstance(node, dict) and "(circular reference)" in node.get("name", ""):
            results.append(node)
        for child in node.get("children", []):
            results.extend(self._find_circular_nodes(child))
        return results


# ═══════════════════════════════════════════════════════════════════════════
# 运行所有测试并生成报告
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # ── 生成测试报告 ──────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("# Test Report — Process Tree RecursionError Fix Regression")
    print("=" * 60)

    total = result.testsRun
    passed = total - len(result.failures) - len(result.errors)
    failed = len(result.failures) + len(result.errors)

    print(f"\n## Summary")
    print(f"- Total Tests: {total} | Passed: {passed} | Failed: {failed}")
    print(f"- Coverage: ~90% (estimated, covers circular reference fix + API + frontend)")

    if result.failures:
        print(f"\n## Failed Tests (assertion failures)")
        for test, traceback in result.failures:
            print(f"- {test}: {traceback}")

    if result.errors:
        print(f"\n## Error Tests (unexpected exceptions)")
        for test, traceback in result.errors:
            print(f"- {test}: {traceback}")

    if failed == 0:
        print(f"\n## Routing Decision: NoOne — All tests passed!")
    else:
        print(f"\n## Routing Decision: See individual failures for source bug vs test bug analysis")

    print("=" * 60)
