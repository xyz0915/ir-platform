import request from './index'

// 1. 语义告警降噪与事件归并
export function correlateIncidents(params = {}) {
  return request.post('/ai/correlate-incidents', null, { params })
}

// 2. 自然语言指挥台
export function aiQuery(query) {
  return request.post('/ai/query', null, { params: { query } })
}

// 3. 攻击故事讲述
export function narrateIncident(params = {}) {
  return request.post('/ai/narrate-incident', null, { params })
}

// 4. 误报自学习
export function markFalsePositive(alertId, reason = '') {
  return request.post('/ai/false-positive', null, { params: { alert_id: alertId, reason } })
}
export function getFalsePositives(page = 1) {
  return request.get('/ai/false-positives', { params: { page } })
}
export function deleteFalsePositive(id) {
  return request.delete(`/ai/false-positives/${id}`)
}

// 5. 预测性沦陷预警
export function getRiskRanking() {
  return request.get('/ai/risk-ranking')
}
