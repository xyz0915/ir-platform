import request from './index'

export default {
  /** 获取草稿列表，支持 status 和 host_id 过滤 */
  getDrafts(params) {
    return request.get('/knowledge/drafts', { params })
  },

  /** 获取内置种子知识数据 */
  getSeeds() {
    return request.get('/knowledge/seeds')
  },

  /** 获取单条知识草稿详情（供证据溯源跳转） */
  getDraftDetail(id) {
    return request.get(`/knowledge/drafts/${id}`)
  },

  /** 批准单条草稿 */
  approveDraft(id) {
    return request.post(`/knowledge/drafts/${id}/approve`)
  },

  /** 拒绝单条草稿 */
  rejectDraft(id) {
    return request.post(`/knowledge/drafts/${id}/reject`)
  },

  /** 撤回已批准/已拒绝草稿 */
  recallDraft(id) {
    return request.post(`/knowledge/drafts/${id}/recall`)
  },

  /** 批量操作 */
  batchAction(ids, action) {
    return request.post('/knowledge/drafts/batch', { ids, action })
  },

  /** 手动导入知识条目 */
  importData(data) {
    return request.post('/knowledge/import', data)
  },

  /** 第三方同步 */
  syncProvider(provider, limit) {
    return request.post(`/knowledge/sync/${provider}`, { limit: limit || 50 })
  }
}
