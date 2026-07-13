import request from './index'

export function getPolicies() {
  return request.get('/policies')
}

export function getPolicy(id) {
  return request.get(`/policies/${id}`)
}

export function createPolicy(params) {
  return request({ method: 'post', url: `/policies?${new URLSearchParams(params).toString()}` })
}

export function updatePolicy(id, params) {
  return request({ method: 'put', url: `/policies/${id}?${new URLSearchParams(params).toString()}` })
}

export function deletePolicy(id) {
  return request.delete(`/policies/${id}`)
}

export function activatePolicy(id) {
  return request.post(`/policies/${id}/activate`)
}

export function deactivatePolicy(id) {
  return request.post(`/policies/${id}/deactivate`)
}

export function duplicatePolicy(id) {
  return request.post(`/policies/${id}/duplicate`)
}

export function setPolicyRules(policyId, ruleIds) {
  return request({
    method: 'put',
    url: `/policies/${policyId}/rules?rule_ids=${ruleIds.join('&rule_ids=')}`
  })
}

export function getRuleSelector(params) {
  return request.get('/rules/selector', { params })
}
