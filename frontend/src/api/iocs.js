import request from './index'

/**
 * IOC 管理 API（T-P1-4，对称于 whitelist）.
 * 仅负责 IOC 指标的入库/查询/删除/批量导入，不参与引擎匹配逻辑。
 *
 * 新增：威胁情报外联（Enrichment）相关接口。
 */
export default {
  getIocs(params = {}) {
    return request.get('/iocs', { params })
  },
  createIoc(data) {
    return request.post('/iocs', data)
  },
  importIocs(items) {
    return request.post('/iocs/import', { items })
  },
  deleteIoc(id) {
    return request.delete(`/iocs/${id}`)
  },
  updateIoc(id, data) {
    return request.put(`/iocs/${id}`, data)
  },

  // ── 威胁情报外联（Enrichment）──────────────────────────────
  // 单条外联查询；body 可选 { provider }
  enrichIoc(id, data = {}) {
    return request.post(`/iocs/${id}/enrich`, data)
  },
  // 批量外联查询；body { ids: [...] } 或 { filter: {...} }
  enrichBatch(payload) {
    return request.post('/iocs/enrich/batch', payload)
  },
  // 获取某 IOC 的威胁情报历史
  getThreatIntel(id) {
    return request.get(`/iocs/${id}/threat-intel`)
  },

  // ── 威胁情报 provider / 运行策略配置 ────────────────────────
  getProviders() {
    return request.get('/threat-intel/providers')
  },
  upsertProvider(data) {
    return request.post('/threat-intel/providers', data)
  },
  deleteProvider(name) {
    return request.delete('/threat-intel/providers', { params: { name } })
  },
  updateProvider(data) {
    return request.put('/threat-intel/providers', data)
  },
  getSettings() {
    return request.get('/threat-intel/settings')
  },
  updateSettings(data) {
    return request.put('/threat-intel/settings', data)
  }
}
