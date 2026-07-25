"""MCP 客户端 — 工具调用入口（MVP-2 真实传输）.

invoke(tool_id, args) → 查 tool → 查 server → get_transport → connect → call_tool → disconnect；
check_idempotency(tool_id, key) → 比对幂等键。
"""

import logging
from typing import Any, Optional

from app.models.mcp import McpServer, McpTool
from app.services.mcp.transport import get_transport

logger = logging.getLogger(__name__)


class MCPClient:
    """MCP 工具调用客户端。"""

    @staticmethod
    def invoke(
        tool_id: str,
        args: Optional[dict] = None,
        run_id: Optional[str] = None,
    ) -> Any:
        """调用指定工具（经传输层真实调用）。

        流程：
        1. McpTool.get_by_id(tool_id) → 获取工具定义
        2. McpServer.get_by_id(server.server_id) → 获取服务器配置
        3. get_transport(server) → 创建对应传输实例
        4. transport.connect() → 建立连接
        5. transport.call_tool(tool.name, args) → 执行调用
        6. transport.disconnect() → 清理
        7. 返回调用结果

        Args:
            tool_id: 工具 ID.
            args: 调用参数（可选）.
            run_id: 运行 ID（可选，用于日志追踪）.

        Returns:
            工具调用结果（字典或列表）.

        Raises:
            ValueError: 工具或服务器不存在.
            RuntimeError: 调用过程中出错.
        """
        # 步骤 1：获取工具定义
        tool = McpTool.get_by_id(tool_id)
        if tool is None:
            raise ValueError(f"工具 {tool_id} 不存在")

        # 步骤 2：获取服务器配置
        server_id = tool.get("server_id")
        if not server_id:
            raise ValueError(f"工具 {tool_id} 未关联 MCP 服务器")
        server = McpServer.get_by_id(server_id)
        if server is None:
            raise ValueError(f"MCP 服务器 {server_id} 不存在")

        tool_name = tool.get("name", "")
        call_args = args or {}
        logger.info(
            "MCPClient.invoke: tool_id=%s, name=%s, server_id=%s",
            tool_id, tool_name, server_id,
        )

        # 步骤 3-6：传输层调用
        transport = None
        try:
            transport = get_transport(server)
            transport.connect()
            result = transport.call_tool(tool_name, call_args)
            logger.info("MCPClient.invoke: %s completed successfully", tool_name)
            return result
        except Exception as exc:
            logger.error(
                "MCPClient.invoke: %s failed: %s", tool_name, exc,
            )
            raise
        finally:
            if transport is not None:
                try:
                    transport.disconnect()
                except Exception as exc:
                    logger.warning("MCPClient.invoke: disconnect error: %s", exc)

    @staticmethod
    def check_idempotency(tool_id: str, idempotency_key: str) -> bool:
        """幂等键校验。

        查 McpTool.get_by_id(tool_id) 的 idempotency_key 字段与传入 key 比对。
        返回 True 表示可安全执行（幂等键匹配），False 表示不匹配。

        Args:
            tool_id: 工具 ID.
            idempotency_key: 待校验的幂等键.

        Returns:
            True 如果幂等键匹配（可安全执行），否则 False.
        """
        tool = McpTool.get_by_id(tool_id)
        if tool is None:
            logger.warning("check_idempotency: tool %s 不存在", tool_id)
            return False

        stored_key = tool.get("idempotency_key", "")
        is_match = bool(stored_key) and stored_key == idempotency_key
        if is_match:
            logger.info(
                "check_idempotency: tool %s 幂等键匹配", tool_id,
            )
        else:
            logger.warning(
                "check_idempotency: tool %s 幂等键不匹配 (expected=%s, got=%s)",
                tool_id, stored_key, idempotency_key,
            )
        return is_match
