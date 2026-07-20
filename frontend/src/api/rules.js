/**
 * 规则管理 API 封装.
 * 对应后端 /api/rules* 端点.
 */
import request from './index'

// ── 规则 CRUD ──
export function listRules(params = {}) {
  return request.get('/rules', { params })
}

export function getRuleStats() {
  return request.get('/rules/stats')
}

export function getRuleCoverage() {
  return request.get('/rules/coverage')
}

export function createRule(data) {
  return request.post('/rules', data)
}

export function updateRule(ruleId, data) {
  return request.put(`/rules/${ruleId}`, data)
}

export function deleteRule(ruleId) {
  return request.delete(`/rules/${ruleId}`)
}

export function bulkEnableRules(data) {
  return request.put('/rules/bulk-enable', data)
}

export function getRuleHistory(ruleId) {
  return request.get(`/rules/${ruleId}/history`)
}

export function revertRule(ruleId, data) {
  return request.post(`/rules/${ruleId}/revert`, data)
}

export function approveRule(ruleId) {
  return request.post(`/rules/${ruleId}/approve`)
}

export function deprecateRule(ruleId) {
  return request.post(`/rules/${ruleId}/deprecate`)
}

// ── 导入导出 ──
export function exportRules() {
  return request.get('/rules/export', { responseType: 'blob' })
}

export function importRules(data) {
  return request.post('/rules/import', data)
}

// ── 测试沙盒（P1-#3） ──
export function testRule(data) {
  return request.post('/rules/test', data)
}

// ── 重置默认规则 ──
export function resetDefaultRules() {
  return request.post('/rules/reset')
}
