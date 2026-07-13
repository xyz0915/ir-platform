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
  }
}
