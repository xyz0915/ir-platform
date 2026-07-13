import request from './index'

export function searchLogs(params = {}) {
  return request.get('/logs/search', { params })
}

export function getLogSummary(hostId = null) {
  const params = {}
  if (hostId) params.host_id = hostId
  return request.get('/logs/stats/summary', { params })
}

export function getLogTimeline(params = {}) {
  return request.get('/logs/stats/timeline', { params })
}

export function getLogSession(sessionId) {
  return request.get(`/logs/session/${sessionId}`)
}

export function logPivot(field, value, hostId = null) {
  const params = { field, value }
  if (hostId) params.host_id = hostId
  return request.get('/logs/pivot', { params })
}

export function getBruteForce(hostId = null, minAttempts = 10) {
  const params = { min_attempts: minAttempts }
  if (hostId) params.host_id = hostId
  return request.get('/logs/patterns/brute-force', { params })
}
