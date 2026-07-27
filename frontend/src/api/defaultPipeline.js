/**
 * 默认闭环流程规则 API 封装（config-default-pipeline）。
 *
 * 端点域沿用 /agents/*（与 /agents/run 同域，便于鉴权复用，架构 §3.3）。
 * 所有请求复用 @/api/index 中已挂载 ir_token 的 axios 实例，
 * 后端统一返回 {code, data, message} 信封。
 */
import request from './index'

/** 列出全部默认规则（管理列表）。 */
export function listDefaultRules(params = {}) {
  return request.get('/agents/default-pipelines', { params })
}

/** 新建默认规则（admin）。 */
export function createDefaultRule(payload) {
  return request.post('/agents/default-pipelines', payload)
}

/** 编辑默认规则（admin）。 */
export function updateDefaultRule(ruleId, payload) {
  return request.put(`/agents/default-pipelines/${ruleId}`, payload)
}

/** 删除默认规则（admin）。 */
export function deleteDefaultRule(ruleId) {
  return request.delete(`/agents/default-pipelines/${ruleId}`)
}

/** resolve 预览：给定事件/覆盖条件，返回将使用的默认流程与命中规则。 */
export function resolveDefaultPipeline(params = {}) {
  return request.get('/agents/default-pipelines/resolve', { params })
}
