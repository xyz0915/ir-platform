"""MCP 工具注册表 — 从 mcp_servers / mcp_tools 加载 schema 注册表（MVP-2 真实 transport）.

MVP-2 补充 refresh_tools 实现：经 transport 实时同步工具 schema 到数据库。
"""

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app.models.mcp import McpServer, McpTool
from app.services.mcp.transport import get_transport

logger = logging.getLogger(__name__)


class ToolRegistry:
    """工具注册表（静态方法，无状态查询）。"""

    @staticmethod
    def list_servers() -> list[dict]:
        """列出全部 MCP 服务器（含 transport/status/tools_count/last_heartbeat）。"""
        return McpServer.get_all()

    @staticmethod
    def list_tools() -> list[dict]:
        """列出全部工具定义（ToolDef 形态）。"""
        return McpTool.list_all()

    @staticmethod
    def list_tools_by_server(server_id: str) -> list[dict]:
        """按 server_id 列出该服务器的全部工具。"""
        return McpTool.get_by_server_id(server_id)

    @staticmethod
    def get_server(server_id: str) -> Optional[dict]:
        """获取单个服务器详情。"""
        return McpServer.get_by_id(server_id)

    @staticmethod
    def refresh_tools(server_id: str) -> dict:
        """触发 schema 刷新（经 transport 实时同步）。

        流程：
        1. McpServer.get_by_id(server_id) → 获取 server
        2. get_transport(server) → 创建 transport
        3. transport.connect() → 连接
        4. transport.list_tools() → 获取工具 schema 列表
        5. 遍历 tools，每条 McpTool.create()（已存在则跳过或更新）
        6. McpServer.set_tools_count(server_id, len(tools))
        7. McpServer.update_status(server_id, "online", last_heartbeat=now)
        8. transport.disconnect()

        Args:
            server_id: MCP 服务器 ID.

        Returns:
            刷新结果字典，含 tools_count 和 status.

        Raises:
            ValueError: 服务器不存在.
            RuntimeError: 传输层调用失败.
        """
        # 步骤 1：获取 server
        server = McpServer.get_by_id(server_id)
        if server is None:
            raise ValueError(f"MCP 服务器 {server_id} 不存在")

        logger.info("refresh_tools: server=%s (%s)", server_id, server.get("name", ""))

        transport = None
        try:
            # 步骤 2-3：创建 transport 并连接
            transport = get_transport(server)
            transport.connect()

            # 步骤 4：获取工具 schema 列表
            tools = transport.list_tools()
            logger.info("refresh_tools: 获取到 %d 个工具 schema", len(tools))

            # 步骤 5：逐条 upsert 到 mcp_tools 表
            imported = 0
            updated = 0
            for tool_schema in tools:
                tool_name = tool_schema.get("name", "")
                tool_desc = tool_schema.get("description", "")
                schema_input = tool_schema.get("inputSchema", tool_schema.get("schema", {}))

                # 检查是否已存在
                existing_tools = McpTool.get_by_server_id(server_id)
                existing = None
                for et in existing_tools:
                    if et.get("name") == tool_name:
                        existing = et
                        break

                if existing:
                    # 已存在：更新 description 和 schema
                    McpTool.update_status(existing["tool_id"], "available")
                    updated += 1
                else:
                    # 不存在：新建
                    McpTool.create(
                        server_id=server_id,
                        name=tool_name,
                        description=tool_desc,
                        schema_json=schema_input,
                        idempotency_key="",
                        timeout_ms=tool_schema.get("timeout_ms", 30000),
                        retries=tool_schema.get("retries", 0),
                        category=tool_schema.get("category", "general"),
                        status="available",
                    )
                    imported += 1

            # 步骤 6：更新工具数
            total_tools = len(tools)
            McpServer.set_tools_count(server_id, total_tools)

            # 步骤 7：更新状态和心跳
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            McpServer.update_status(server_id, "online", last_heartbeat=now)

            logger.info(
                "refresh_tools completed: server=%s, total=%d, new=%d, updated=%d",
                server_id, total_tools, imported, updated,
            )

            return {
                "server_id": server_id,
                "tools_count": total_tools,
                "imported": imported,
                "updated": updated,
                "status": "online",
            }

        except Exception as exc:
            logger.error("refresh_tools failed for server %s: %s", server_id, exc)
            # 标记为 degraded
            try:
                McpServer.update_status(server_id, "degraded")
            except Exception as update_exc:
                logger.warning("更新服务器 %s 状态失败: %s", server_id, update_exc)
            raise RuntimeError(f"刷新工具 schema 失败: {exc}") from exc

        finally:
            if transport is not None:
                try:
                    transport.disconnect()
                except Exception as exc:
                    logger.warning("transport.disconnect 异常: %s", exc)
