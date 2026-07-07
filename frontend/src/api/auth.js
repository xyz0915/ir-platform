import request from './index'

export default {
  login(username, password) {
    return request.post('/auth/login', { username, password })
  },
  getMe() {
    return request.get('/auth/me')
  }
}
