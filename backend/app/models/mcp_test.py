"""F7 MCP 模型 CRUD 单元测试 — McpServer / McpTool.

运行：cd backend && ../venv/Scripts/python.exe -m unittest app.models.mcp_test -v
"""
import os
import sys
import unittest

_test_dir = os.path.dirname(os.path.abspath(__file__))
_backend_root = os.path.abspath(os.path.join(_test_dir, '..', '..'))
if _backend_root not in sys.path:
    sys.path.insert(0, _backend_root)

from app.models.mcp import McpServer, McpTool


class TestMcpServer(unittest.TestCase):
    """McpServer CRUD 测试."""

    def setUp(self):
        """每测试前清理测试数据（删除创建的测试服务器）。"""
        self._cleanup()

    def tearDown(self):
        self._cleanup()

    def _cleanup(self):
        servers = McpServer.get_all()
        for s in servers:
            try:
                from app.database import get_connection
                with get_connection() as conn:
                    conn.execute("DELETE FROM mcp_tools WHERE server_id = ?", (s["server_id"],))
                    conn.execute("DELETE FROM mcp_servers WHERE server_id = ?", (s["server_id"],))
            except Exception:
                pass

    def test_create_and_get(self):
        """创建 McpServer 后应按 server_id 可取回."""
        srv = McpServer.create(
            name="test-mcp",
            transport="stdio",
            command="python -m my_mcp_server",
            args_json=["--port", "8080"],
        )
        self.assertIn("server_id", srv)
        self.assertEqual(srv["name"], "test-mcp")
        self.assertEqual(srv["transport"], "stdio")
        # 按 server_id 查询
        fetched = McpServer.get_by_id(srv["server_id"])
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["name"], "test-mcp")

    def test_get_all(self):
        """get_all 应返回列表."""
        McpServer.create(name="srv-a", transport="sse", url="http://localhost:9090")
        McpServer.create(name="srv-b", transport="stdio", command="/bin/mcp")
        all_s = McpServer.get_all()
        self.assertGreaterEqual(len(all_s), 2)

    def test_update_status(self):
        """update_status 应更新状态、工具数、心跳."""
        srv = McpServer.create(name="status-test", transport="stdio", command="echo hi")
        updated = McpServer.update_status(srv["server_id"], "online", tools_count=5, last_heartbeat="2026-07-24T12:00:00Z")
        self.assertEqual(updated["status"], "online")
        self.assertEqual(updated["tools_count"], 5)
        self.assertEqual(updated["last_heartbeat"], "2026-07-24T12:00:00Z")

    def test_set_tools_count(self):
        """set_tools_count 应更新工具数并将状态置为 online."""
        srv = McpServer.create(name="cnt-test", transport="stdio", command="echo")
        updated = McpServer.set_tools_count(srv["server_id"], 3)
        self.assertEqual(updated["tools_count"], 3)
        self.assertEqual(updated["status"], "online")


class TestMcpTool(unittest.TestCase):
    """McpTool CRUD 测试."""

    def setUp(self):
        self.server = McpServer.create(name="tool-test-srv", transport="stdio", command="echo hello")
        self.server_id = self.server["server_id"]

    def tearDown(self):
        try:
            from app.database import get_connection
            with get_connection() as conn:
                conn.execute("DELETE FROM mcp_tools WHERE server_id = ?", (self.server_id,))
                conn.execute("DELETE FROM mcp_servers WHERE server_id = ?", (self.server_id,))
        except Exception:
            pass

    def test_create_and_get(self):
        """创建 McpTool 后应按 tool_id 可取回."""
        tool = McpTool.create(
            server_id=self.server_id,
            name="list-files",
            description="列出目录文件",
            schema_json='{"type":"object","properties":{"dir":{"type":"string"}}}',
            category="filesystem",
            timeout_ms=15000,
        )
        self.assertIn("tool_id", tool)
        self.assertEqual(tool["name"], "list-files")
        self.assertEqual(tool["category"], "filesystem")
        fetched = McpTool.get_by_id(tool["tool_id"])
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["name"], "list-files")

    def test_get_by_server_id(self):
        """get_by_server_id 应返回该服务器的所有工具."""
        McpTool.create(server_id=self.server_id, name="tool-a")
        McpTool.create(server_id=self.server_id, name="tool-b")
        tools = McpTool.get_by_server_id(self.server_id)
        self.assertGreaterEqual(len(tools), 2)

    def test_list_all(self):
        """list_all 应返回全部工具."""
        McpTool.create(server_id=self.server_id, name="tool-x")
        all_t = McpTool.list_all()
        self.assertGreaterEqual(len(all_t), 1)

    def test_update_status(self):
        """update_status 应更新工具状态."""
        tool = McpTool.create(server_id=self.server_id, name="st-test")
        updated = McpTool.update_status(tool["tool_id"], "disabled")
        self.assertEqual(updated["status"], "disabled")


if __name__ == "__main__":
    unittest.main()
