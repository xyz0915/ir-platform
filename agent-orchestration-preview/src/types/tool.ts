import type { ID } from './common';

/** 工具状态 */
export type ToolStatus = 'available' | 'degraded' | 'disabled';

/** 工具定义 —— 对齐 F1 ToolRegistry（schema / 幂等键 / 超时 / 重试） */
export interface ToolDef {
  tool_id: ID;
  name: string;
  description: string;
  /** JSON Schema（用于 AgentForm 工具 schema 预览） */
  schema: Record<string, unknown>;
  /** 幂等键（反空壳门槛：防止重复执行破坏性动作） */
  idempotency_key: string;
  timeout_ms: number;
  retries: number;
  category: string;
  /** 所属 MCP 服务器 id（可选，内置工具可为空） */
  mcp_server_id?: ID;
  status: ToolStatus;
}

/** MCP 服务器传输方式 */
export type McpTransport = 'stdio' | 'sse';

/** MCP 服务器状态 */
export type McpServerStatus = 'online' | 'offline' | 'degraded';

/** MCP 服务器（工具生态接入点） */
export interface McpServer {
  server_id: ID;
  name: string;
  transport: McpTransport;
  status: McpServerStatus;
  tools_count: number;
  last_heartbeat: string;
}
