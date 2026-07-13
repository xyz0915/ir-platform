/**
 * 应急报告 CRUD API 服务
 *
 * 对应后端 report.py 中 incident_reports 表的操作。
 * 注意：POST/PUT 使用 Query Params（非 JSON body），axios 需特殊处理。
 */
import request from './index'

export default {
  /**
   * 报告列表
   * GET /api/reports?status=&page=&page_size=
   */
  list(status = 'all', page = 1, pageSize = 50) {
    return request.get('/reports', { params: { status, page, page_size: pageSize } })
  },

  /**
   * 报告详情
   * GET /api/reports/{id}
   */
  get(id) {
    return request.get(`/reports/${id}`)
  },

  /**
   * 新建报告
   * POST /api/reports?title=&report_type=&audience=&case_id=&host_id=&created_by=
   */
  create(params) {
    return request.post('/reports', null, { params })
  },

  /**
   * 更新报告
   * PUT /api/reports/{id}?title=&summary=&evidence=&... 
   * 后端使用 Query Params，需设置 Content-Type 并传 params
   */
  update(id, params) {
    return request.put(`/reports/${id}`, null, { params })
  },

  /**
   * 删除报告
   * DELETE /api/reports/{id}
   */
  remove(id) {
    return request.delete(`/reports/${id}`)
  },

  /**
   * 提交审核 (draft → review)
   * POST /api/reports/{id}/submit
   */
  submit(id) {
    return request.post(`/reports/${id}/submit`)
  },

  /**
   * 发布 (review → published)
   * POST /api/reports/{id}/publish
   */
  publish(id) {
    return request.post(`/reports/${id}/publish`)
  },

  /**
   * 按主机分组获取报告列表
   * GET /api/reports/grouped-by-host?status=
   */
  listGroupedByHost(status = 'all') {
    return request.get('/reports/grouped-by-host', { params: { status } })
  },

  /**
   * 用最新 AI 结果重新填充草稿（支持增量更新）
   * POST /api/reports/{id}/regenerate-from-ai?sections=
   */
  regenerateFromAi(reportId, sections = null) {
    const params = {}
    if (sections && sections.length > 0) {
      params.sections = sections.join(',')
    }
    return request.post(`/reports/${reportId}/regenerate-from-ai`, null, { params })
  },

  /**
   * 版本差异对比
   * GET /api/reports/{id}/diff
   */
  diffReport(reportId) {
    return request.get(`/reports/${reportId}/diff`)
  },

  /**
   * 获取导出 URL（直接打开链接）
   */
  getDocxExportUrl(reportId) { return `/api/reports/${reportId}/export/docx` },
  getMarkdownExportUrl(reportId) { return `/api/reports/${reportId}/export/markdown` },
  getJsonExportUrl(reportId) { return `/api/reports/${reportId}/export/json` },

  /**
   * 获取审计日志
   * GET /api/reports/{id}/audit-logs
   */
  getAuditLogs(reportId) { return request.get(`/reports/${reportId}/audit-logs`) }
}
