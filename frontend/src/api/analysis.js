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
  getProcessTree(hostId) {
    return request.get(`/hosts/${hostId}/process-tree`)
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
  getUsb(hostId) {
    return request.get(`/hosts/${hostId}/usb`)
  },
  getRemoteControl(hostId) {
    return request.get(`/hosts/${hostId}/remote-control`)
  }
}
