import request from './index'

export function getAuditLogs(params) {
  return request.get('/audit-logs', { params })
}

export function cleanupAuditLogs() {
  return request.delete('/audit-logs/cleanup')
}

export function getAuditLogActionTypes() {
  return request.get('/audit-logs/action-types')
}
