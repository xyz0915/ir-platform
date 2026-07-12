import request from './index'

export function getAlerts(params = {}) {
  return request.get('/alerts', { params })
}

export function getAlert(id) {
  return request.get(`/alerts/${id}`)
}

export function acknowledgeAlert(id) {
  return request.put(`/alerts/${id}/acknowledge`)
}

export function resolveAlert(id) {
  return request.put(`/alerts/${id}/resolve`)
}

export function dismissAlert(id, reason = '') {
  return request.put(`/alerts/${id}/dismiss?reason=${encodeURIComponent(reason)}`)
}

export function getAlertStats() {
  return request.get('/alerts/stats/summary')
}

export function getAlertTrend(hours = 24) {
  return request.get('/alerts/stats/trend', { params: { hours } })
}

export function getOnlineHosts() {
  return request.get('/hosts/online')
}

export function getHostsStatus() {
  return request.get('/hosts/online-status')
}
