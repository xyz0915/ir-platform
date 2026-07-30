import request from './index'

/**
 * 获取工具列表（分页 + 搜索 + 分类筛选）
 * @param {Object} params - { keyword, category, page, page_size, sort_by, sort_order }
 * @returns {Promise<{code: number, data: {total: number, items: Array, page: number, page_size: number}}>}
 */
export function getToolList(params) {
  return request.get('/tools', { params })
}

/**
 * 获取统计概览
 * @returns {Promise<{code: number, data: {total_tools, total_downloads, today_new, category_count}}>}
 */
export function getToolStats() {
  return request.get('/tools/stats')
}

/**
 * 获取分类列表（含各分类计数）
 * @returns {Promise<{code: number, data: {categories: Array}}>}
 */
export function getToolCategories() {
  return request.get('/tools/categories')
}

/**
 * 获取工具详情（含版本历史）
 * @param {number} id
 * @returns {Promise<{code: number, data: Object}>}
 */
export function getToolDetail(id) {
  return request.get(`/tools/${id}`)
}

/**
 * 上传新工具
 * @param {FormData} data - 含 name, description, category, version, tags, change_log, file, doc_file
 * @returns {Promise<{code: number, data: Object}>}
 */
export function uploadTool(data) {
  return request.post('/tools', data, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

/**
 * 更新工具信息
 * @param {number} id
 * @param {FormData|Object} data
 * @returns {Promise<{code: number, data: Object}>}
 */
export function updateTool(id, data) {
  return request.put(`/tools/${id}`, data, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

/**
 * 删除工具
 * @param {number} id
 * @returns {Promise<{code: number, data: {deleted: boolean}}>}
 */
export function deleteTool(id) {
  return request.delete(`/tools/${id}`)
}

/**
 * 发布新版本
 * @param {number} id
 * @param {FormData} data - 含 version, change_log, file, doc_file
 * @returns {Promise<{code: number, data: Object}>}
 */
export function publishVersion(id, data) {
  return request.post(`/tools/${id}/versions`, data, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

/**
 * 下载工具文件（触发浏览器下载）
 * @param {number} id
 * @param {number} [versionId] - 可选，指定版本
 */
export function downloadTool(id, versionId) {
  const token = localStorage.getItem('ir_token')
  const base = import.meta.env.VITE_API_BASE || ''
  let url = `${base}/api/tools/${id}/download?token=${token}`
  if (versionId) {
    url += `&version_id=${versionId}`
  }
  window.open(url, '_blank')
}

/**
 * 查看操作文档（新窗口打开）
 * @param {number} id
 * @param {number} [versionId] - 可选，指定版本
 */
export function viewDoc(id, versionId) {
  const token = localStorage.getItem('ir_token')
  const base = import.meta.env.VITE_API_BASE || ''
  let url = `${base}/api/tools/${id}/doc?token=${token}`
  if (versionId) {
    url += `&version_id=${versionId}`
  }
  window.open(url, '_blank')
}

/**
 * 获取文档内容（供 DocPreview 组件使用）
 * @param {number} id
 * @param {number} [versionId]
 * @returns {Promise<{code: number, data: {content: string, file_type: string}}>}
 */
export function getDocContent(id, versionId) {
  const params = {}
  if (versionId) params.version_id = versionId
  return request.get(`/tools/${id}/doc`, { params })
}
