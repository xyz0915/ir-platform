import request from './index'

/**
 * 分析中心事件 API 封装.
 * 对应后端 /api/analysis/events* 端点.
 */

// 事件列表（筛选 + 排序 + 分页）
export function getEvents(params = {}) {
  return request.get('/analysis/events', { params })
}

// 筛选统计
export function getEventStats(params = {}) {
  return request.get('/analysis/events/stats', { params })
}

// 事件详情
export function getEventDetail(eventId) {
  return request.get(`/analysis/events/${eventId}`)
}

// 单条状态变更
export function updateEventStatus(eventId, data) {
  return request.patch(`/analysis/events/${eventId}/status`, data)
}

// 批量状态变更
export function batchUpdateStatus(data) {
  return request.patch('/analysis/events/batch-status', data)
}

// 指派负责人
export function assignEvent(eventId, data) {
  return request.patch(`/analysis/events/${eventId}/assign`, data)
}

// 批量指派
export function batchAssign(data) {
  return request.patch('/analysis/events/batch-assign', data)
}

// 攻击链时间轴数据
export function getTimelineData(params = {}) {
  return request.get('/analysis/events/timeline', { params })
}

// 关联事件
export function getRelatedEvents(eventId) {
  return request.get(`/analysis/events/${eventId}/related`)
}

// 状态变更历史
export function getEventHistory(eventId) {
  return request.get(`/analysis/events/${eventId}/history`)
}

// 导出 CSV
export function exportEventsCsv(params = {}) {
  return request.get('/analysis/events/export/csv', {
    params,
    responseType: 'blob',
  })
}

// 筛选元数据（案件/主机/规则统计）
export function getEventFilters(params = {}) {
  return request.get('/analysis/events/filters', { params })
}

// 手动触发存量事件规则匹配
export function batchMatchRules(data) {
  return request.post('/analysis/events/batch-match-rules', data)
}

// 批量写入（内部/Agent 使用）
export function ingestEvents(data) {
  return request.post('/analysis/events/ingest', data)
}

// 事件时间线上下文
export function getEventContext(eventId, minutes = 5) {
  return request.get(`/analysis/events/${eventId}/context`, { params: { minutes } })
}

// 主机统计
export function getEventHostStats(eventId) {
  return request.get(`/analysis/events/${eventId}/host-stats`)
}

// 影响范围
export function getEventImpact(eventId) {
  return request.get(`/analysis/events/${eventId}/impact`)
}

// 处置记录
export function getDispositions(eventId) {
  return request.get(`/analysis/events/${eventId}/dispositions`)
}

// 添加处置记录
export function addDisposition(eventId, data) {
  return request.post(`/analysis/events/${eventId}/dispositions`, data)
}

// v2.1 前端字段展示：必填/辅助分级 + 证据双视图
export function getEventDisplay(eventId) {
  return request.get(`/analysis/events/${eventId}/display`)
}

// AI 降噪研判（触发当前案件所有已匹配事件的分析）
export function triggerAiNoiseReduce(caseId, hostId = null) {
  const params = { case_id: caseId }
  if (hostId) params.host_id = hostId
  return request.post('/ai/noise-reduce', null, { params, timeout: 200000 })
}

// 进程树
export function getProcessTree(eventId) {
  return request.get(`/analysis/events/${eventId}/process-tree`)
}

// AI 研判打标（对选中事件批量研判，写回 ai_verdict；挂载于 /api/security-events）
export function triggerEventVerdict(eventIds, opts = {}) {
  const data = { event_ids: eventIds }
  if (opts.force !== undefined) data.force = opts.force
  if (opts.threshold !== undefined) data.confidence_threshold = opts.threshold
  return request.post('/security-events/ai-verdict', data, { timeout: 600000 })
}
