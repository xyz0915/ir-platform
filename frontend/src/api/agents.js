import request from './index'

export function getAgents(params) {
  return request.get('/agents', { params })
}

export function getAgentStats() {
  return request.get('/agents/stats')
}
