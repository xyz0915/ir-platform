/**
 * M4 工具与 MCP 真实适配器（F7 后端就绪后启用）。
 * USE_MOCK.tools=false 时由 facade 切换至此，调用方零改动。
 * 端点 URL 对齐后端 MVP-1 只读聚合（07 §2 / T7）。
 *
 * 设计依据：07-arch-decomposition.md §2 / §5（T7）。
 */
import request from '@/api/index'

const BASE = '/mcp' // F7 后端真实路由前缀：main.py 注册 mcp.router 时 prefix="/api/mcp"；
// 因 @/api/index 的 axios 实例 baseURL 已为 '/api'，这里只用相对路径 '/mcp'，
// 拼接后请求为 /api/mcp/tools（而非 /api/api/mcp/tools，否则 404）。

export function listTools() {
  return request({ url: `${BASE}/tools`, method: 'GET' })
}
export function listMcpServers() {
  return request({ url: `${BASE}/servers`, method: 'GET' })
}
