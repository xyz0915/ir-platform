import request from './index'

export function getUsers(params) {
  return request.get('/users', { params })
}

export function createUser(data) {
  return request.post('/users', data)
}

export function updateUser(id, data) {
  return request.put(`/users/${id}`, data)
}

export function deleteUser(id) {
  return request.delete(`/users/${id}`)
}

export function resetPassword(id, data) {
  return request.post(`/users/${id}/reset-password`, data)
}

export function toggleUserActive(id) {
  return request.post(`/users/${id}/toggle-active`)
}
