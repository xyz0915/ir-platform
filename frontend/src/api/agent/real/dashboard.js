/**
 * M1 Dashboard 趋势 / 护栏拦截数 真实适配器。
 *
 * getTrend：指向真实聚合端点 /api/agents/dashboard（agent_dashboard.py:41-117），
 * 返回 { running_agents, success_rate, pending_hitl, recent_runs,
 *        trend: [{ ts, success_rate }] }，trend 形状与 store 完全匹配。
 * （A9：原先把全局态势 /api/dashboard/stats 的 rule_hits 序列近似为 success_rate，
 *  趋势图失真；现改为真实按日 agent_runs 成功率。）
 *
 * getGuardrailBlocks：后端无 /api/dashboard/guardrail-blocks 路由（A1）。
 * 真实命中数据在 /api/agent-guardrails/hits（GuardrailHit.list_all()），
 * 客户端按 !passed 计数，store 契约保持 data 为 number。
 */
import request from '@/api/index'

export function getTrend() {
  return request({ url: '/agents/dashboard', method: 'GET' }).then((res) => {
    const trend = (res && res.data && Array.isArray(res.data.trend)) ? res.data.trend : []
    return { code: 0, data: trend, message: 'success' }
  })
}

/** 护栏拦截数 = hits 中 !passed 的计数（行为差异：mock 在无策略命中时也记 none
 *  hit；后端仅命中策略才记 Hit → 真实 hits 列表更少、更准确）。 */
export async function getGuardrailBlocks() {
  const res = await request({ url: '/agent-guardrails/hits', method: 'GET' })
  const hits = (res && res.data) || []
  return { code: 0, data: hits.filter((h) => !h.passed).length, message: 'success' }
}
