import request from './index'

export function getSystemSettings() {
  return request.get('/settings')
}

export function updateSystemSetting(key, data) {
  return request.put(`/settings/${key}`, data)
}
