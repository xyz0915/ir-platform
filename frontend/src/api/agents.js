import request from './index'

export function getAgents(params) {
  return request.get('/agents', { params })
}

export function getAgentStats(params) {
  return request.get('/agents/stats', { params })
}

export function generateAgentToken(hostId) {
  return request.post(`/agents/${hostId}/token`)
}
