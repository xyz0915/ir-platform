"""MCP 模型 — mcp_servers / mcp_tools 表 CRUD（§2）.

遵循现有 KnowledgeDraft 风格：原生 SQLite + get_connection() + 静态方法返回 dict。

- McpServer：MCP 服务器注册表。
- McpTool：工具注册表（对齐 01-api-spec.md §4 ToolDef）。
"""

import json
import logging
import uuid
from typing import Any, Optional

from app.database import get_connection

logger = logging.getLogger(__name__)


class McpServer:
    """MCP 服务器注册表 CRUD。"""

    @staticmethod
    def _default_json(value: Any, default: str = "{}") -> str:
        """将对象序列化为 JSON 字符串，None 用 default 兜底。"""
        if value is None:
            return default
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False)

    @staticmethod
    def create(
        name: str,
        transport: str = "stdio",
        status: str = "offline",
        command: Optional[str] = None,
        args_json: Any = None,
        url: Optional[str] = None,
        env_json: Any = None,
        schema_json: Any = None,
        server_id: Optional[str] = None,
    ) -> dict:
        """创建 MCP 服务器（server_id 可选，缺省自动生成）。"""
        sid = server_id or f"mcp://{uuid.uuid4().hex[:8]}"
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO mcp_servers
                    (server_id, name, transport, status, command, args_json,
                     url, env_json, schema_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sid,
                    name,
                    transport,
                    status,
                    command,
                    McpServer._default_json(args_json, "[]"),
                    url,
                    McpServer._default_json(env_json, "{}"),
                    McpServer._default_json(schema_json, "{}"),
                ),
            )
            rid = cursor.lastrowid
            row = conn.execute(
                "SELECT * FROM mcp_servers WHERE id = ?", (rid,)
            ).fetchone()
        return dict(row)

    @staticmethod
    def get_by_id(server_id: str) -> Optional[dict]:
        """按 server_id（业务主键）获取。"""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM mcp_servers WHERE server_id = ?", (server_id,)
            ).fetchone()
            return dict(row) if row else None

    @staticmethod
    def get_all() -> list[dict]:
        """列出全部 MCP 服务器。"""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM mcp_servers ORDER BY created_at ASC, id ASC"
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def update_status(
        server_id: str,
        status: str,
        tools_count: Optional[int] = None,
        last_heartbeat: Optional[str] = None,
    ) -> Optional[dict]:
        """更新服务器状态 / 工具数 / 心跳（MVP-2 心跳探测用）。"""
        clauses = ["status = ?", "updated_at = datetime('now')"]
        values: list[Any] = [status]
        if tools_count is not None:
            clauses.append("tools_count = ?")
            values.append(tools_count)
        if last_heartbeat is not None:
            clauses.append("last_heartbeat = ?")
            values.append(last_heartbeat)
        values.append(server_id)
        with get_connection() as conn:
            conn.execute(
                f"UPDATE mcp_servers SET {', '.join(clauses)} WHERE server_id = ?",
                values,
            )
        return McpServer.get_by_id(server_id)

    @staticmethod
    def set_tools_count(server_id: str, count: int) -> Optional[dict]:
        """设置服务器已注册工具数。"""
        return McpServer.update_status(server_id, "online", tools_count=count)


class McpTool:
    """工具注册表 CRUD。"""

    @staticmethod
    def create(
        server_id: str,
        name: str,
        description: str = "",
        schema_json: Any = None,
        idempotency_key: str = "",
        timeout_ms: int = 30000,
        retries: int = 0,
        category: str = "general",
        status: str = "available",
        tool_id: Optional[str] = None,
    ) -> dict:
        """创建工具（tool_id 可选，缺省自动生成）。"""
        tid = tool_id or f"tool-{uuid.uuid4().hex[:10]}"
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO mcp_tools
                    (tool_id, server_id, name, description, schema_json,
                     idempotency_key, timeout_ms, retries, category, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tid,
                    server_id,
                    name,
                    description,
                    McpTool._default_json(schema_json, "{}"),
                    idempotency_key,
                    timeout_ms,
                    retries,
                    category,
                    status,
                ),
            )
            rid = cursor.lastrowid
            row = conn.execute(
                "SELECT * FROM mcp_tools WHERE id = ?", (rid,)
            ).fetchone()
        return dict(row)

    @staticmethod
    def _default_json(value: Any, default: str = "{}") -> str:
        if value is None:
            return default
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False)

    @staticmethod
    def get_by_id(tool_id: str) -> Optional[dict]:
        """按 tool_id（业务主键）获取。"""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM mcp_tools WHERE tool_id = ?", (tool_id,)
            ).fetchone()
            return dict(row) if row else None

    @staticmethod
    def get_by_server_id(server_id: str) -> list[dict]:
        """列出某服务器的全部工具。"""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM mcp_tools WHERE server_id = ? ORDER BY id ASC",
                (server_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def list_all() -> list[dict]:
        """列出全部工具。"""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM mcp_tools ORDER BY server_id ASC, id ASC"
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def update_status(tool_id: str, status: str) -> Optional[dict]:
        """更新工具状态（available/degraded/disabled）。"""
        with get_connection() as conn:
            conn.execute(
                "UPDATE mcp_tools SET status = ?, updated_at = datetime('now') "
                "WHERE tool_id = ?",
                (status, tool_id),
            )
        return McpTool.get_by_id(tool_id)
