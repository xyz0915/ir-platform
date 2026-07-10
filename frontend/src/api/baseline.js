// 差分基线 API 封装（v1.3.0 支柱③ R3-1）
// 对应后端 /api/baselines 路由

import request from './index'

// 上传主机差分基线（agent_baselines）
export function uploadBaseline(hostId, payload) {
  // payload: { baseline_json: {...}, source?, note? }
  return request.post(`/baselines/${hostId}`, payload)
}

// 读取主机最新基线
export function getLatestBaseline(hostId) {
  return request.get(`/baselines/${hostId}`)
}

// 读取主机基线列表
export function listBaselines(hostId) {
  return request.get(`/baselines/${hostId}/list`)
}

// 删除基线
export function deleteBaseline(baselineId) {
  return request.delete(`/baselines/${baselineId}`)
}
