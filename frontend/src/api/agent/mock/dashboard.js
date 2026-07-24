/**
 * M1 Dashboard Mock 适配器。
 *
 * 暴露：getTrend() / getGuardrailBlocks()
 * trend 为近 7 日成功率曲线（真实无聚合端点）；guardrailBlocks 由 guardrail 命中记录计数。
 *
 * 设计依据：01-api-spec.md §1 / §11.3。
 */
import { clone, delay, ok } from './util'
import { listHits } from './guardrail'

/** 近 7 日成功率趋势（Mock） */
function buildTrend() {
  return Array.from({ length: 7 }).map((_, i) => {
    const base = 88 + ((i * 13) % 9) - 2
    return {
      ts: new Date(Date.now() - (6 - i) * 86400000).toISOString(),
      success_rate: Math.max(80, Math.min(99, base)),
    }
  })
}

export async function getTrend() {
  await delay()
  return ok(clone(buildTrend()))
}

/** 护栏拦截数（guardrail 命中中 !passed 的计数） */
export async function getGuardrailBlocks() {
  await delay()
  const hits = (await listHits()).data || []
  return ok(hits.filter((h) => !h.passed).length)
}
