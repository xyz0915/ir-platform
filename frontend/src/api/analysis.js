import request from './index'

export default {
  analyze(hostId) {
    return request.post(`/hosts/${hostId}/analyze`, {}, { timeout: 120000 })
  },
  getAnalysis(hostId) {
    return request.get(`/hosts/${hostId}/analysis`)
  },
  getProfile(hostId) {
    return request.get(`/hosts/${hostId}/profile`)
  },
  getTimeline(hostId, params = {}) {
    return request.get(`/hosts/${hostId}/timeline`, { params })
  },
  getTimelineStats(hostId) {
    return request.get(`/hosts/${hostId}/timeline/stats`)
  },
  getIocHits(hostId) {
    return request.get(`/hosts/${hostId}/ioc-hits`)
  },
  getPersistence(hostId) {
    return request.get(`/hosts/${hostId}/persistence`)
  },
  getSuspiciousConnections(hostId) {
    return request.get(`/hosts/${hostId}/suspicious-connections`)
  },
  enrichSuspiciousConnections(hostId) {
    return request.post(`/hosts/${hostId}/suspicious-connections/enrich`)
  },
  getAbnormalProcesses(hostId) {
    return request.get(`/hosts/${hostId}/abnormal-processes`)
  },
  getProcessTree(hostId, params = {}) {
    // params 可携带 { enrich: 1 } 以请求增强字段（severity/parent_name/connections/攻击链等）。
    // 缺省（无 params）时返回与历史版本逐字段一致的数据，旧组件兼容。
    return request.get(`/hosts/${hostId}/process-tree`, { params })
  },
  getStartupItems(hostId) {
    return request.get(`/hosts/${hostId}/startup-items`)
  },
  getUsers(hostId) {
    return request.get(`/hosts/${hostId}/users`)
  },
  getServices(hostId) {
    return request.get(`/hosts/${hostId}/services`)
  },
  getServiceRisk(hostId) {
    return request.get(`/hosts/${hostId}/service-risk`)
  },
  getUsb(hostId) {
    return request.get(`/hosts/${hostId}/usb`)
  },
  getRemoteControl(hostId) {
    return request.get(`/hosts/${hostId}/remote-control`)
  },
  getNetworkConnections(hostId) {
    return request.get(`/hosts/${hostId}/network-connections`)
  },
  enrichNetworkConnections(hostId) {
    return request.post(`/hosts/${hostId}/network-connections/enrich`)
  },
  getFileHashes(hostId) {
    return request.get(`/hosts/${hostId}/file-hashes`)
  },
  getWmiSubscriptions(hostId) {
    return request.get(`/hosts/${hostId}/wmi-subscriptions`)
  },
  getRegistryKeys(hostId) {
    return request.get(`/hosts/${hostId}/registry-keys`)
  },
  // T04: 更新时间线事件状态
  updateTimelineEvent(eventId, data) {
    return request.patch(`/analysis/timeline/${eventId}`, data)
  },
  // T05: 多主机对比
  getCompareTimeline(hostIds) {
    return request.get('/analysis/timeline/compare', { params: { host_ids: hostIds.join(',') } })
  },
}
