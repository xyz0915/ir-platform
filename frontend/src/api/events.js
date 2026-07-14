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
