/**
 * M8 可观测性 trace/log 真实适配器（F7 后端就绪后启用）。
 * USE_MOCK.observability=false 时由 facade 切换至此，调用方零改动。
 * 端点 URL 为文档化约定（对齐 01-api-spec.md §8）。
 */
import request from '@/api/index'

const BASE = '/agent-runs' // TODO: 对齐后端 F7 真实路由

export function getRun(runId) {
  return request({ url: `${BASE}/${runId}/trace`, method: 'GET' })
}
