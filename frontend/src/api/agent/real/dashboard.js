/**
 * M1 Dashboard 趋势 真实适配器（F1 趋势聚合端点就绪后启用）。
 *
 * USE_MOCK.dashboardTrend=false 时由 facade 切换至此，调用方零改动。
 * getTrend 指向全局态势 /api/dashboard/stats，把 trend.labels + 各 series
 * 映射为 store 期望的 [{ts, success_rate}] 形态（07 §5.4）。
 *
 * 说明：全局态势接口的趋势是「告警量 / 规则命中」逐日序列，并非 agent 成功率；
 * B 档将其 rule_hits 序列映射为 success_rate 占位值（store 仅需 [{ts, success_rate}]
 * 形态）。真正的 agent 维度成功率趋势由后端 F1 聚合（/api/agents/dashboard）单独提供。
 *
 * getGuardrailBlocks 仍由 USE_MOCK.dashboardGuardrailBlocks 门控，B 档默认走 Mock
 * （F8 真实命中聚合待后续翻键启用）。
 *
 * 设计依据：07-arch-decomposition.md §5.4 / §4.1。
 */
import request from '@/api/index'

const BASE = '/dashboard' // F1 全局态势聚合前缀（07 §5.4）

export function getTrend() {
  return request({ url: `${BASE}/stats`, method: 'GET' }).then((res) => {
    const trend = (res && res.data && res.data.trend) || {}
    const labels = trend.labels || []
    const series = trend.rule_hits || []
    const mapped = labels.map((ts, i) => ({
      ts,
      success_rate: series[i] != null ? series[i] : 0,
    }))
    return { code: 0, data: mapped, message: 'success' }
  })
}

/** 护栏拦截数（F8 未就绪，默认仍走 Mock；保留真实占位待翻键启用） */
export function getGuardrailBlocks() {
  return request({ url: `${BASE}/guardrail-blocks`, method: 'GET' })
}
