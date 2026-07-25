/**
 * M5 记忆与 RAG 真实适配器（F3 后端就绪后启用）。
 * USE_MOCK.memory=false 时由 facade 切换至此，调用方零改动。
 * 端点对齐：GET /api/knowledge/drafts?status=approved（07 §5.2 / §4.2）。
 *
 * 映射（方案 a，零后端成本）：将 approved 知识草稿映射为 KnowledgeBase 形态，
 * 使 store 对 Mock / 真实两条路径拿到同一 shape（store 零改动）。
 *   draft_{id}      → kb_id
 *   title           → name
 *   category        → vector_store 占位
 *   severity        → 透传（附加字段）
 *   reviewed_at||created_at → updated_at
 */
import request from '@/api/index'

const BASE = '/knowledge' // F3 后端真实路由（07 §5.2）

export function listKnowledgeBases() {
  return request({ url: `${BASE}/drafts?status=approved`, method: 'GET' }).then((res) => {
    const drafts = (res && res.data) || []
    const mapped = drafts.map((d) => ({
      kb_id: `draft_${d.id}`,
      name: d.title,
      embedding_model: 'n/a', // 草稿无向量模型概念
      vector_store: d.category || 'knowledge_draft', // 占位
      doc_count: 1, // 每条草稿视为 1 个知识项
      updated_at: d.reviewed_at || d.created_at || '',
      severity: d.severity, // 透传给 UI 标签
    }))
    return { code: 0, data: mapped, message: 'success' }
  })
}
