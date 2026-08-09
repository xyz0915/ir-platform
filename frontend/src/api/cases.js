import request from './index'

export default {
  list(page = 1, size = 20, search = '') {
    return request.get('/cases', { params: { page, size, search } })
  },
  create(data) {
    return request.post('/cases', data)
  },
  get(id) {
    return request.get(`/cases/${id}`)
  },
  // ── 案件详情聚合态势（告警/资产/处置/取证/IOC/TTP/AI/时间线）──
  summary(id) {
    return request.get(`/cases/${id}/summary`)
  },
  update(id, data) {
    return request.put(`/cases/${id}`, data)
  },
  delete(id) {
    return request.delete(`/cases/${id}`)
  },
  // ── 清空案件（被遗忘权）────────────────────
  purgePreview(id) {
    return request.get(`/cases/purge-preview/${id}`)
  },
  purge(data) {
    return request.post('/cases/purge', data)
  },
  getCasesWithHosts() {
    return request.get('/cases/with-hosts')
  }
}
