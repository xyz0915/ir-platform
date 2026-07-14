/** 日志检索模块 API 封装（8 个端点） */

import request from './index'

const BASE = '/logs'

/**
 * 导入 Agent JSON 数据
 * POST /api/logs/import
 */
export function importJson(data) {
  return request.post(`${BASE}/import`, data)
}

/**
 * 导入记录列表（分页+筛选）
 * GET /api/logs/imports
 */
export function listImports(params) {
  return request.get(`${BASE}/imports`, { params })
}

/**
 * 导入详情
 * GET /api/logs/imports/{id}
 */
export function getImport(id) {
  return request.get(`${BASE}/imports/${id}`)
}

/**
 * 全文检索 + 结构化筛选
 * GET /api/logs/search
 */
export function searchLogs(params) {
  return request.get(`${BASE}/search`, { params })
}

/**
 * 高级搜索（字段运算符语法）
 * GET /api/logs/search/advanced
 */
export function searchAdvanced(params) {
  return request.get(`${BASE}/search/advanced`, { params })
}

/**
 * 返回纯文本 JSON
 * GET /api/logs/search/raw
 */
export function getRawJson(params) {
  return request.get(`${BASE}/search/raw`, { params })
}

/**
 * 导出搜索结果
 * GET /api/logs/search/export
 * 返回 Blob 用于文件下载
 */
export async function exportSearch(params) {
  const response = await request.get(`${BASE}/search/export`, {
    params,
    responseType: 'blob',
  })
  // request 拦截器可能包裹了 data，需要判断
  if (response instanceof Blob) return response
  if (response?.data instanceof Blob) return response.data
  return response
}

/**
 * 一键生成 SecurityEvent
 * POST /api/logs/imports/{id}/to-event
 */
export function toEvent(id) {
  return request.post(`${BASE}/imports/${id}/to-event`)
}

/**
 * 获取日志量趋势数据
 * GET /api/logs/trend
 */
export function getTrend(params) {
  return request.get(`${BASE}/trend`, { params })
}
