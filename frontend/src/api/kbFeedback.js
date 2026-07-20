import request from './index'

// P2-H：知识库自进化闭环（误报 → 抑制 → 沉淀）
// 后端前缀 /api/kb（见 backend/app/api/knowledge.py）

/** 提交反馈：误报 / 真阳性 / 抑制 */
export function submitKbFeedback(data) {
  return request({ url: '/kb/feedback', method: 'post', data })
}

/** 列出反馈（支持 feedback_type / applied / 分页） */
export function listKbFeedback(params) {
  return request({ url: '/kb/feedback', method: 'get', params })
}

/** 触发自进化（可选 feedback_id；缺省处理全部未沉淀反馈） */
export function evolveKb(data) {
  return request({ url: '/kb/evolve', method: 'post', data: data || {} })
}

/** 获取自进化统计与沉淀条目 */
export function getKbStats() {
  return request({ url: '/kb/stats', method: 'get' })
}
