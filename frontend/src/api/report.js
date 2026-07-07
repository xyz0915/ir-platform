import request from './index'

export default {
  getHtmlReportUrl(hostId) {
    return `/api/hosts/${hostId}/report`
  },
  getPdfReportUrl(hostId) {
    return `/api/hosts/${hostId}/report/pdf`
  },
  downloadPdf(hostId) {
    return request.get(`/hosts/${hostId}/report/pdf`, {
      responseType: 'blob',
      timeout: 120000
    })
  }
}
