/**
 * M4 工具与 MCP 真实适配器（F1 后端就绪后启用）。
 * USE_MOCK.tools=false 时由 facade 切换至此，调用方零改动。
 * 端点 URL 为文档化约定（对齐 01-api-spec.md §4）。
 */
import request from '@/api/index'

const BASE = '/mcp' // TODO: 对齐后端 F1 真实路由

export function listTools() {
  return request({ url: `${BASE}/tools`, method: 'GET' })
}
export function listMcpServers() {
  return request({ url: `${BASE}/servers`, method: 'GET' })
}
