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
  update(id, data) {
    return request.put(`/cases/${id}`, data)
  },
  delete(id) {
    return request.delete(`/cases/${id}`)
  }
}
