/**
 * M5 记忆与 RAG 真实适配器（P0：真实向量库统计）。
 * USE_MOCK.memory=false 时由 facade 切换至此，调用方零改动。
 * 端点对齐：GET /api/knowledge/bases（P0 改造后返回聚合结构，07 §5 P0 方案）。
 *
 * 消费结构（统一信封 {code, data, message}）：
 *   data.bases  → 真实向量库条目数组（collection 可用时 1 条 ir_rules，否则 []）
 *   data.stats  → 向量库统计 { doc_count, embedding_model, vector_store,
 *                              index_updated_at, approved_drafts, collection_ready }
 *   data.drafts → 已批准草稿精简列表（id/title/category/severity/reviewed_at）
 *
 * 适配器做 shape 归一（缺字段给安全默认值），store 负责拆分到状态。
 */
import request from '@/api/index'

const BASE = '/knowledge' // F3 后端真实路由（07 §5.2）

export function listKnowledgeBases() {
  return request({ url: `${BASE}/bases`, method: 'GET' }).then((res) => {
    const payload = (res && res.data) || {}
    const data = payload && typeof payload === 'object' ? payload : {}
    return {
      code: 0,
      data: {
        bases: Array.isArray(data.bases) ? data.bases : [],
        stats: data.stats && typeof data.stats === 'object' ? data.stats : {},
        drafts: Array.isArray(data.drafts) ? data.drafts : [],
      },
      message: 'success',
    }
  })
}
