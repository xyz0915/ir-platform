/**
 * M7 护栏与安全 真实适配器（F8 后端就绪后启用）。
 *
 * 当前 USE_MOCK.guardrail=true 时 facade 不走此文件；后端 F8 落地后，
 * 将 mock-config.js 的 guardrail 置 false 即自动切换，调用方零改动。
 * 端点 URL 为文档化约定（对齐 01-api-spec.md §7），后端定稿后以此为准。
 */
import request from '@/api/index'

const BASE = '/agent-guardrails' // TODO: 对齐后端 F8 真实路由

export function listPolicies() {
  return request({ url: BASE, method: 'GET' })
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
export function evaluate(action, ctx) {
  return request({ url: `${BASE}/evaluate`, method: 'POST', data: { action, ctx } })
}
export function listHits() {
  return request({ url: `${BASE}/hits`, method: 'GET' })
}
