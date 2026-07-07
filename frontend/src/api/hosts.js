import request from './index'

export default {
  listByCase(caseId) {
    return request.get(`/cases/${caseId}/hosts`)
  },
  create(caseId, data) {
    return request.post(`/cases/${caseId}/hosts`, data)
  },
  get(id) {
    return request.get(`/hosts/${id}`)
  },
  delete(id) {
    return request.delete(`/hosts/${id}`)
  },
  importJson(id, file) {
    const formData = new FormData()
    formData.append('file', file)
    return request.post(`/hosts/${id}/import`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000
    })
  },
  getImportRecords(id) {
    return request.get(`/hosts/${id}/import-records`)
  },
  downloadAgent(osType) {
    return request.get(`/agent/download/${osType}`, {
      responseType: 'blob'
    })
  }
}
