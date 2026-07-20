import request from './index'

// P0-B：规则自生成 + 影子运行 + 自动调优 + 人审启用

export function generateRuleDraft(data) {
  return request({ url: '/rules/generate', method: 'post', data })
}

export function listRuleDrafts(params) {
  return request({ url: '/rules/drafts', method: 'get', params })
}

export function runShadow(draftId) {
  return request({ url: `/rules/drafts/${draftId}/shadow`, method: 'post' })
}

export function getShadowStats(draftId) {
  return request({ url: `/rules/drafts/${draftId}/shadow-stats`, method: 'get' })
}

export function tuneDraft(draftId, data) {
  return request({ url: `/rules/drafts/${draftId}/tune`, method: 'post', data })
}

export function enableDraft(draftId) {
  return request({ url: `/rules/drafts/${draftId}/enable`, method: 'post' })
}

export function rejectDraft(draftId, data) {
  return request({ url: `/rules/drafts/${draftId}/reject`, method: 'post', data })
}
