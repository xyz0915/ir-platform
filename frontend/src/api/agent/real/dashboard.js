/**
 * M1 Dashboard 趋势/护栏拦截数 真实适配器（后端聚合端点就绪后启用）。
 * USE_MOCK.dashboardTrend=false 时由 facade 切换至此，调用方零改动。
 * 端点 URL 为文档化约定（对齐 01-api-spec.md §1）。
 */
import request from '@/api/index'

const BASE = '/agent-dashboard' // TODO: 对齐后端聚合端点

export function getTrend() {
  return request({ url: `${BASE}/trend`, method: 'GET' })
}
export function getGuardrailBlocks() {
  return request({ url: `${BASE}/guardrail-blocks`, method: 'GET' })
}
