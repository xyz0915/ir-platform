/**
 * M8 可观测性 trace/log 真实适配器（后端已就绪，无缺口）。
 * USE_MOCK.observability=false 时由 facade 切换至此，调用方零改动。
 * 端点对齐：GET /api/agents/runs/{id}（真实详情含 steps[]，取 run.steps 作 trace）。
 */
import request from '@/api/index'

const BASE = '/agents/runs' // M8 后端真实路由（07 §5.1）

export function getRun(runId) {
  // 去掉 /trace，直接取 run 详情；steps 由 store 映射为 trace（07 §5.1 / 06 §7 风险7）
  return request({ url: `${BASE}/${runId}`, method: 'GET' })
}
