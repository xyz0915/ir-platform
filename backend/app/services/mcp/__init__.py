"""MCP 工具服务层（§2.2）.

导出：
  - ToolRegistry：MVP-1 实装（纯 DB 读取聚合）。
  - MCPClient：MVP-2 启用（真实调用入口，当前仅占位接口）。
"""

from app.services.mcp.client import MCPClient
from app.services.mcp.registry import ToolRegistry

__all__ = ["ToolRegistry", "MCPClient"]
