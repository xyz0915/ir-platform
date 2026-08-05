/**
 * M7 护栏与安全 真实适配器（F8 后端已就绪，USE_MOCK.guardrail=false 启用）。
 *
 * BASE 保持相对路径：axios baseURL='/api'（api/index.js:6）拼接后即
 * /api/agent-guardrails（与 real/tools.js 同模式），无需改为绝对路径。
 */
import request from '@/api/index'

const BASE = '/agent-guardrails'

/**
 * whitelist 归一化：后端 GuardrailPolicy.get_all() 返回的 whitelist 是 JSON 字符串，
 * 前端表单期望数组 → 解析；解析失败/空值回退 []。
 * @param {unknown} v
 * @returns {Array}
 */
function parseList(v) {
  if (Array.isArray(v)) return v
  if (!v) return []
  try { return JSON.parse(v) } catch { return [] }
}

/** 策略列表：whitelist 字符串 → 数组（与 mock 形状对齐） */
export async function listPolicies() {
  const res = await request({ url: BASE, method: 'GET' })
  const items = (res.data || []).map((p) => ({ ...p, whitelist: parseList(p.whitelist) }))
  return { code: 0, data: items, message: 'success' }
}

export function createPolicy(policy) {
  return request({ url: BASE, method: 'POST', data: policy })
}
export function updatePolicy(policy) {
  return request({ url: `${BASE}/${policy.policy_id}`, method: 'PUT', data: policy })
}
export function deletePolicy(policyId) {
  return request({ url: `${BASE}/${policyId}`, method: 'DELETE' })
}
/**
 * 评估动作。载荷字段对齐后端 EvaluateRequest（agent_guardrails.py: action + context）。
 * @param {string} action
 * @param {object} [ctx] 触发上下文（如 { run_id }），原实现发送 { action, ctx } 时
 *                       ctx 被 pydantic 静默丢弃，导致 HITL 上下文校验上下文丢失。
 */
export function evaluate(action, ctx) {
  return request({
    url: `${BASE}/evaluate`,
    method: 'POST',
    data: { action, context: ctx || {} },
  }).then((res) => {
    // 归一化：后端无匹配策略时 policy_id=null，前端期望 ''（与 mock 一致）
    if (res && res.data && res.data.policy_id == null) res.data.policy_id = ''
    return res
  })
}
export function listHits() {
  return request({ url: `${BASE}/hits`, method: 'GET' })
}
