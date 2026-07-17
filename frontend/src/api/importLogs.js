/**
 * 手工日志导入 API 封装.
 * 对应后端 /api/hosts/{hostId}/import-logs* 端点.
 */
import request from './index'

/**
 * 上传日志文件并触发导入.
 * @param {number} hostId 主机 ID
 * @param {File} file 上传的文件
 * @param {string} logType 日志类型（'auto' 自动检测 | 'evtx' | 'nginx_access' 等）
 * @param {boolean} confirmed 是否确认导入
 * @returns {Promise}
 */
export function uploadLogFile(hostId, file, logType = 'auto', confirmed = true) {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('log_type', logType)
  formData.append('confirmed', confirmed ? 'true' : 'false')
  return request.post(`/hosts/${hostId}/import-logs`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: confirmed ? 300000 : 60000,  // 预览超时较短
  })
}

/**
 * 预览日志文件解析结果（前 10 条，不入库）.
 * @param {number} hostId 主机 ID
 * @param {File} file 上传的文件
 * @param {string} logType 日志类型（'auto' | 'evtx' | 'nginx_access' 等）
 * @returns {Promise}
 */
export function previewLogFile(hostId, file, logType = 'auto') {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('log_type', logType)
  return request.post(`/hosts/${hostId}/import-logs/preview`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 60000,
  })
}

/**
 * 获取主机的导入记录列表.
 * @param {number} hostId 主机 ID
 * @param {object} params 查询参数 { page, page_size }
 * @returns {Promise}
 */
export function getImportRecords(hostId, params = {}) {
  return request.get(`/hosts/${hostId}/import-logs/records`, { params })
}

/**
 * 获取单条导入记录详情及结果明细.
 * @param {number} hostId 主机 ID
 * @param {number} recordId 导入记录 ID
 * @returns {Promise}
 */
export function getImportRecordDetail(hostId, recordId) {
  return request.get(`/hosts/${hostId}/import-logs/records/${recordId}`)
}

/**
 * 查询异步导入任务状态.
 * @param {number} hostId 主机 ID
 * @param {number|string} taskId 任务 ID（导入记录 ID）
 * @returns {Promise}
 */
export function getImportTaskStatus(hostId, taskId) {
  return request.get(`/hosts/${hostId}/import-logs/tasks/${taskId}`)
}
