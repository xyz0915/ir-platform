import type { McpServer, ToolDef } from '@/types';
import { clone, delay, ok, type ApiResponse } from './util';

/** ToolRegistry 工具清单（含 schema / 幂等键 / 超时 / 重试） */
const TOOLS: ToolDef[] = [
  {
    tool_id: 'tool-process-query',
    name: '进程查询',
    description: '查询主机进程树、命令行与父进程关系。',
    schema: {
      type: 'object',
      properties: {
        host: { type: 'string', description: '目标主机名' },
        pid: { type: 'number', description: '进程 ID（可选）' },
      },
      required: ['host'],
    },
    idempotency_key: 'proc:query:{host}:{pid}',
    timeout_ms: 5000,
    retries: 1,
    category: '主机取证',
    mcp_server_id: 'mcp-edr',
    status: 'available',
  },
  {
    tool_id: 'tool-netflow',
    name: '网络流量抓取',
    description: '拉取指定主机的出入向连接与字节数。',
    schema: {
      type: 'object',
      properties: {
        host: { type: 'string' },
        window_min: { type: 'number', description: '时间窗（分钟）' },
      },
      required: ['host'],
    },
    idempotency_key: 'netflow:pull:{host}:{window_min}',
    timeout_ms: 8000,
    retries: 2,
    category: '网络取证',
    mcp_server_id: 'mcp-net',
    status: 'available',
  },
  {
    tool_id: 'tool-log-search',
    name: '日志检索',
    description: '在 SIEM/日志库按查询条件检索事件。',
    schema: {
      type: 'object',
      properties: {
        query: { type: 'string' },
        top: { type: 'number', default: 100 },
      },
      required: ['query'],
    },
    idempotency_key: 'log:search:{query}:{top}',
    timeout_ms: 6000,
    retries: 2,
    category: '日志',
    status: 'available',
  },
  {
    tool_id: 'tool-ti-lookup',
    name: '威胁情报查询',
    description: '查询 IP/域名/文件哈希的威胁情报评分。',
    schema: {
      type: 'object',
      properties: { ioc: { type: 'string' } },
      required: ['ioc'],
    },
    idempotency_key: 'ti:lookup:{ioc}',
    timeout_ms: 4000,
    retries: 2,
    category: '情报',
    mcp_server_id: 'mcp-ti',
    status: 'available',
  },
  {
    tool_id: 'tool-host-isolate',
    name: '主机隔离',
    description: '将失陷主机从网络隔离（高危破坏性动作）。',
    schema: {
      type: 'object',
      properties: { host: { type: 'string' } },
      required: ['host'],
    },
    idempotency_key: 'host:isolate:{host}',
    timeout_ms: 10000,
    retries: 0,
    category: '处置',
    mcp_server_id: 'mcp-edr',
    status: 'available',
  },
  {
    tool_id: 'tool-fw-block',
    name: '防火墙阻断',
    description: '下发防火墙阻断策略（高危动作）。',
    schema: {
      type: 'object',
      properties: { cidr: { type: 'string' }, direction: { type: 'string', enum: ['in', 'out'] } },
      required: ['cidr', 'direction'],
    },
    idempotency_key: 'fw:block:{cidr}:{direction}',
    timeout_ms: 7000,
    retries: 1,
    category: '处置',
    mcp_server_id: 'mcp-fw',
    status: 'degraded',
  },
  {
    tool_id: 'tool-edr-quarantine',
    name: 'EDR 隔离文件',
    description: '将可疑文件送隔离区并停止相关进程。',
    schema: {
      type: 'object',
      properties: { host: { type: 'string' }, path: { type: 'string' } },
      required: ['host', 'path'],
    },
    idempotency_key: 'edr:quarantine:{host}:{path}',
    timeout_ms: 6000,
    retries: 1,
    category: '处置',
    mcp_server_id: 'mcp-edr',
    status: 'available',
  },
  {
    tool_id: 'tool-sandbox-detonation',
    name: '沙箱 Detonation',
    description: '在沙箱中执行样本并采集行为。',
    schema: {
      type: 'object',
      properties: { sample_ref: { type: 'string' } },
      required: ['sample_ref'],
    },
    idempotency_key: 'sandbox:detonate:{sample_ref}',
    timeout_ms: 60000,
    retries: 0,
    category: '取证',
    mcp_server_id: 'mcp-sandbox',
    status: 'available',
  },
  {
    tool_id: 'tool-ioc-extract',
    name: 'IOC 提取',
    description: '从文本/报告中抽取结构化 IOC。',
    schema: {
      type: 'object',
      properties: { text: { type: 'string' } },
      required: ['text'],
    },
    idempotency_key: 'ioc:extract:{hash}',
    timeout_ms: 4000,
    retries: 1,
    category: '情报',
    status: 'available',
  },
  {
    tool_id: 'tool-db-snapshot',
    name: '数据库快照',
    description: '对关键库做只读快照（回滚点前置）。',
    schema: {
      type: 'object',
      properties: { db: { type: 'string' } },
      required: ['db'],
    },
    idempotency_key: 'db:snapshot:{db}',
    timeout_ms: 15000,
    retries: 1,
    category: '处置',
    mcp_server_id: 'mcp-db',
    status: 'disabled',
  },
];

/** MCP 服务器状态 */
const MCP_SERVERS: McpServer[] = [
  {
    server_id: 'mcp-edr',
    name: 'EDR-MCP',
    transport: 'sse',
    status: 'online',
    tools_count: 3,
    last_heartbeat: '2026-07-06T17:00:40.000Z',
  },
  {
    server_id: 'mcp-net',
    name: 'NetVis-MCP',
    transport: 'sse',
    status: 'online',
    tools_count: 1,
    last_heartbeat: '2026-07-06T17:00:38.000Z',
  },
  {
    server_id: 'mcp-ti',
    name: 'ThreatIntel-MCP',
    transport: 'stdio',
    status: 'online',
    tools_count: 1,
    last_heartbeat: '2026-07-06T17:00:35.000Z',
  },
  {
    server_id: 'mcp-fw',
    name: 'Firewall-MCP',
    transport: 'sse',
    status: 'degraded',
    tools_count: 1,
    last_heartbeat: '2026-07-06T16:58:12.000Z',
  },
  {
    server_id: 'mcp-sandbox',
    name: 'Sandbox-MCP',
    transport: 'stdio',
    status: 'offline',
    tools_count: 1,
    last_heartbeat: '2026-07-06T16:40:00.000Z',
  },
  {
    server_id: 'mcp-db',
    name: 'DB-MCP',
    transport: 'sse',
    status: 'online',
    tools_count: 1,
    last_heartbeat: '2026-07-06T17:00:30.000Z',
  },
];

/** 读取工具清单 */
export const getTools = async (): Promise<ApiResponse<ToolDef[]>> => {
  await delay();
  return ok(clone(TOOLS));
};

/** 读取 MCP 服务器 */
export const getMcpServers = async (): Promise<ApiResponse<McpServer[]>> => {
  await delay();
  return ok(clone(MCP_SERVERS));
};

/** 按 id 读取工具 */
export const getToolById = (id: string): ToolDef | undefined =>
  TOOLS.find((t) => t.tool_id === id);

/** 同步读取工具清单（供顶部全局搜索候选，mock 场景可接受） */
export const listToolsSync = (): ToolDef[] => TOOLS;
