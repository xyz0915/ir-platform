/**
 * 多智能体编排 + HITL 审批 API 封装（P0-A）。
 *
 * 注意：本文件与已存在的 ``api/agents.js``（Agent 客户端注册/心跳/统计）互不冲突，
 * 这里仅封装「编排闭环」相关的 6 个端点，路径统一前缀 /agents。
 * 所有请求复用 ``@/api/index`` 中已挂载 ir_token 的 axios 实例，
 * 后端统一返回 ``{code, data, message}`` 信封。
 */
import request from './index'
import {
  listDefaultRules,
  createDefaultRule,
  updateDefaultRule,
  deleteDefaultRule,
  resolveDefaultPipeline,
} from './defaultPipeline'

/**
 * 启动一次多智能体闭环（triage → investigation → responder[HITL] → reporter）。
 * @param {{event_id?: string, event_ids?: string[], case_id?: number}} payload
 * @returns {Promise<{run_id:string, status:string, stage:string, [k]:any}>}
 */
export function createAgentRun(payload = {}) {
  // 编排闭环需串行执行 3 个 LLM 调用（triage + investigation + responder），
  // 每调用约 10-15s，总耗时可能超过默认的 30s 全局超时，故显式设为 3 分钟。
  return request.post('/agents/run', payload, { timeout: 180000 })
}

/**
 * 分页列出 agent_runs。
 * @param {{status?:string, priority?:string, page?:number, page_size?:number}} params
 */
export function listAgentRuns(params = {}) {
  return request.get('/agents/runs', { params })
}

/**
 * 获取单次运行详情（含 steps[]）。
 * @param {string} runId
 */
export function getAgentRun(runId) {
  return request.get(`/agents/runs/${runId}`)
}

/**
 * HITL 批准（仅管理员）。
 * @param {string} runId
 * @param {{approval_id:number, decided_by?:string}} payload
 */
export function approveAgentRun(runId, payload) {
  return request.post(`/agents/runs/${runId}/approve`, payload)
}

/**
 * HITL 拒绝（仅管理员）。
 * @param {string} runId
 * @param {{approval_id:number, reason?:string}} payload
 */
export function rejectAgentRun(runId, payload) {
  return request.post(`/agents/runs/${runId}/reject`, payload)
}

/**
 * 列出待审批的 HITL 记录（仅管理员）。
 * @param {string} [status='pending']
 */
export function listPendingApprovals(status = 'pending') {
  return request.get('/agents/approvals', { params: { status } })
}

/**
 * 获取 SSE 流 URL
 * @param {string} runId
 * @returns {string}
 */
export function getSSEUrl(runId) {
  return `/api/agents/runs/${runId}/stream`
}

// ── 默认闭环流程（config-default-pipeline）──

/** 列出全部默认规则。 */
export function listDefaultRulesApi(params = {}) {
  return listDefaultRules(params)
}

/** 新建默认规则。 */
export function createDefaultRuleApi(payload) {
  return createDefaultRule(payload)
}

/** 编辑默认规则。 */
export function updateDefaultRuleApi(ruleId, payload) {
  return updateDefaultRule(ruleId, payload)
}

/** 删除默认规则。 */
export function deleteDefaultRuleApi(ruleId) {
  return deleteDefaultRule(ruleId)
}

/** resolve 预览：返回将使用的默认流程与命中规则。 */
export function resolveDefaultPipelineApi(params = {}) {
  return resolveDefaultPipeline(params)
}
