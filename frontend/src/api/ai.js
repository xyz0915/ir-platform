// AI 分析 API 封装

import request from './index'

// 获取AI配置
export function getAiConfig() {
  return request.get('/ai/config')
}

// 保存AI配置
export function saveAiConfig(data) {
  return request.post('/ai/config', data)
}

// 开启/关闭AI功能
export function toggleAi(enabled) {
  return request.post('/ai/toggle', { enabled })
}

// 一键AI分析
export function aiAnalyze(hostId) {
  return request.post(`/ai/analyze/${hostId}`, null, { timeout: 120000 })
}

// 获取AI分析报告
export function getAiReport(hostId) {
  return request.get(`/ai/report/${hostId}`)
}

// 删除AI分析报告
export function deleteAiReport(hostId) {
  return request.delete(`/ai/report/${hostId}`)
}
