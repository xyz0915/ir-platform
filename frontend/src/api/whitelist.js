import request from './index'

export default {
  getWhitelist(params = {}) {
    return request.get('/whitelist', { params })
  },
  createWhitelist(data) {
    return request.post('/whitelist', null, { params: data })
  },
  updateWhitelist(id, data) {
    return request.put(`/whitelist/${id}`, null, { params: data })
  },
  deleteWhitelist(id) {
    return request.delete(`/whitelist/${id}`)
  }
}
