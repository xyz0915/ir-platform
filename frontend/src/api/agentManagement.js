/**
 * 智能体管理 Phase 2 — API 封装。
 *
 * 所有请求复用 @/api/index 中已挂载 ir_token 的 axios 实例，
 * 后端统一返回 {code, data, message} 信封。
 */
import request from './index'

// ── Agent CRUD ──

/** 列出 Agent（可按启用状态筛选）。 */
export function listAgents(enabledOnly = true) {
  return request.get('/agent-management/agents', { params: { enabled_only: enabledOnly } })
}

/** 注册新 Agent。 */
export function createAgent(data) {
  return request.post('/agent-management/agents', data)
}

/** 更新 Agent 配置。 */
export function updateAgent(name, data) {
  return request.put(`/agent-management/agents/${name}`, data)
}

/** 注销 Agent。 */
export function deleteAgent(name) {
  return request.delete(`/agent-management/agents/${name}`)
}

/** 查询依赖图（逗号分隔的 Agent 名称）。 */
export function getDependencyGraph(agents) {
  return request.get('/agent-management/agents/deps', { params: { agents: agents.join(',') } })
}

// ── Pipeline 执行 ──

/** 验证管道配置。 */
export function validatePipeline(agents) {
  return request.post('/agent-management/pipeline/validate', { agents })
}

/** 执行管道（异步，返回 run_id）。 */
export function runPipeline(eventId, agents, useCache = true) {
  return request.post(
    '/agent-management/pipeline/run',
    { event_id: eventId, agents, use_cache: useCache },
    { timeout: 180000 },
  )
}

/** 查询管道运行状态。 */
export function getRunStatus(runId) {
  return request.get(`/agent-management/pipeline/run/${runId}`)
}

/** 取消运行。 */
export function cancelRun(runId) {
  return request.post(`/agent-management/pipeline/run/${runId}/cancel`)
}

/** 恢复 HITL 暂停的管道。 */
export function resumeRun(runId, approved, comment = '') {
  return request.post(`/agent-management/pipeline/run/${runId}/resume`, { approved, comment })
}

/** 获取 SSE 流 URL（非 request 调用，返回路径字符串）。 */
export function getPipelineSSEUrl(runId) {
  return `/agent-management/pipeline/run/${runId}/stream`
}

// ── 预置模板 ──

/** 列出预置管道模板。 */
export function listPresets() {
  return request.get('/agent-management/pipeline/presets')
}

/** 保存管道为预置模板。 */
export function createPreset(name, description, agents) {
  return request.post('/agent-management/pipeline/presets', { name, description, agents })
}

/** 删除预置模板。 */
export function deletePreset(presetId) {
  return request.delete(`/agent-management/pipeline/presets/${presetId}`)
}

/** 更新预置模板（如修改状态为 published）。 */
export function updatePreset(presetId, data) {
  return request.put(`/agent-management/pipeline/presets/${presetId}`, data)
}

// ── Phase 3 · 单节点调试 / 分支模拟 ──

/** 单节点独立执行（真实 / 模拟）。 */
export function runNode(payload) {
  return request.post('/agent-management/pipeline/node/run', payload, { timeout: 180000 })
}

/** 分支模拟：纯图计算返回 active/pruned 下游。 */
export function simulateBranch(payload) {
  return request.post('/agent-management/pipeline/node/simulate-branch', payload)
}

/** 查询单节点调试历史。 */
export function getNodeRuns(params = {}) {
  return request.get('/agent-management/pipeline/node/runs', { params })
}

// ── 缓存管理 ──

/** 查看缓存统计。 */
export function getCacheStats() {
  return request.get('/agent-management/cache/stats')
}

/** 失效缓存（agentName = null 时全量失效）。 */
export function invalidateCache(agentName = null) {
  return request.post('/agent-management/cache/invalidate', { agent_name: agentName })
}
