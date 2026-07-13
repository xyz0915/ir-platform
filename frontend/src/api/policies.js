import request from './index'

export function getPolicies() {
  return request.get('/policies')
}

export function getPolicy(id) {
  return request.get(`/policies/${id}`)
}

export function createPolicy(params) {
  return request.post('/policies', null, { params })
}

export function updatePolicy(id, params) {
  return request.put(`/policies/${id}`, null, { params })
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
  return request.put(`/policies/${policyId}/rules`, null, {
    params: { rule_ids: ruleIds }
  })
}

export function getRuleSelector(params) {
  return request.get('/rules/selector', { params })
}
