// 事件归并 / 根因分析 API 封装（第③批 T-D2 / P1-D · P1-G）
import request from './index'

// 语义级事件归并簇列表（severity 过滤 + 分页）
export function listIncidentClusters(params = {}) {
  return request.get('/ai/incidents/clusters', { params })
}

// 触发事件归并：mode = keyword | semantic（后端 correlate-incidents 为 POST，参数走 query）
export function correlateIncidents(params = {}) {
  const query = new URLSearchParams()
  if (params.host_id != null) query.set('host_id', params.host_id)
  if (params.time_window_minutes != null) {
    query.set('time_window_minutes', params.time_window_minutes)
  }
  if (params.mode) query.set('mode', params.mode)
  const qs = query.toString()
  return request.post(`/ai/correlate-incidents${qs ? `?${qs}` : ''}`)
}

// 根因归因：{ host_id, event_id? }
export function getRootCause(payload = {}) {
  return request.post('/analysis/root-cause', {
    host_id: payload.host_id,
    event_id: payload.event_id || null,
  })
}
