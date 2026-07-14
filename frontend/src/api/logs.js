/** 日志分析中心 + 日志检索模块 API 封装 */

import request from './index'

const BASE = '/logs'

// ==============================
// 日志分析中心（旧模块）API
// ==============================

/** 日志搜索（日志分析中心） */
export function searchLogs(params) {
  return request.get(`${BASE}/search`, { params })
}

/** 日志摘要统计 */
export function getLogSummary(params) {
  return request.get(`${BASE}/stats/summary`, { params })
}

/** 日志时间线统计 */
export function getLogTimeline(params) {
  return request.get(`${BASE}/stats/timeline`, { params })
}

/** 暴力破解检测 */
export function getBruteForce(params) {
  return request.get(`${BASE}/patterns/brute-force`, { params })
}

/** 日志透视查询 */
export function logPivot(params) {
  return request.get(`${BASE}/pivot`, { params })
}

// ==============================
// 日志检索（新模块 v2）API
// ==============================

/** 导入 Agent JSON 数据 */
export function importJson(data) {
  return request.post(`${BASE}/import`, data)
}

/** 导入记录列表（分页+筛选） */
export function listImports(params) {
  return request.get(`${BASE}/imports`, { params })
}

/** 导入详情 */
export function getImport(id) {
  return request.get(`${BASE}/imports/${id}`)
}

/** 高级搜索（字段运算符语法） */
export function searchAdvanced(params) {
  return request.get(`${BASE}/search/advanced`, { params })
}

/** 返回纯文本 JSON */
export function getRawJson(params) {
  return request.get(`${BASE}/search/raw`, { params })
}

/** 导出搜索结果 */
export async function exportSearch(params) {
  const response = await request.get(`${BASE}/search/export`, {
    params,
    responseType: 'blob',
  })
  if (response instanceof Blob) return response
  if (response?.data instanceof Blob) return response.data
  return response
}

/** 一键生成 SecurityEvent */
export function toEvent(id) {
  return request.post(`${BASE}/imports/${id}/to-event`)
}

/** 获取日志量趋势数据 */
export function getTrend(params) {
  return request.get(`${BASE}/trend`, { params })
}
