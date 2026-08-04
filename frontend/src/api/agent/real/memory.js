/**
 * M5 记忆与 RAG 真实适配器（P0：真实向量库统计；P2：长期记忆 agent_memories）。
 * USE_MOCK.memory=false 时由 facade 切换至此，调用方零改动。
 * 端点对齐：
 *   - GET /api/knowledge/bases（P0 改造后返回聚合结构，07 §5 P0 方案）
 *   - /api/memories 前缀（P2 长期记忆，p2-design.md §5）
 *
 * 消费结构（统一信封 {code, data, message}）：
 *   data.bases  → 真实向量库条目数组（collection 可用时 1 条 ir_rules，否则 []）
 *   data.stats  → 向量库统计 { doc_count, embedding_model, vector_store,
 *                              index_updated_at, approved_drafts, collection_ready }
 *   data.drafts → 已批准草稿精简列表（id/title/category/severity/reviewed_at）
 *
 * 长期记忆（P2）信封：
 *   GET    /api/memories           → data: { items: AgentMemory[], total, page, page_size }
 *   GET    /api/memories/search    → data: { items: AgentMemory[], total }
 *   POST   /api/memories           → data: AgentMemory（含 id / created_at）
 *   DELETE /api/memories/{id}      → data: { deleted: true }
 *
 * 适配器做 shape 归一（缺字段给安全默认值），store 负责拆分到状态。
 */
import request from '@/api/index'

const BASE = '/knowledge' // F3 后端真实路由（07 §5.2）
const MEMORY_BASE = '/memories' // P2 长期记忆真实路由（p2-design.md §5）

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

/** 列表/筛选/分页：GET /api/memories。params 支持 event_id/host_id/agent_name/memory_type/q/page/page_size。 */
export function listMemories(params = {}) {
  return request({ url: `${MEMORY_BASE}`, method: 'GET', params }).then((res) => {
    const payload = (res && res.data) || {}
    const data = payload && typeof payload === 'object' ? payload : {}
    return {
      code: 0,
      data: {
        items: Array.isArray(data.items) ? data.items : [],
        total: Number(data.total) || 0,
        page: Number(data.page) || 1,
        page_size: Number(data.page_size) || 10,
      },
      message: 'success',
    }
  })
}

/** 关键词检索：GET /api/memories/search?q=...。params 支持 event_id/host_id/agent_name/memory_type/limit。 */
export function searchMemories(q, params = {}) {
  return request({
    url: `${MEMORY_BASE}/search`,
    method: 'GET',
    params: { q: q || '', ...params },
  }).then((res) => {
    const payload = (res && res.data) || {}
    const data = payload && typeof payload === 'object' ? payload : {}
    return {
      code: 0,
      data: {
        items: Array.isArray(data.items) ? data.items : [],
        total: Number(data.total) || 0,
      },
      message: 'success',
    }
  })
}

/** 手动写入：POST /api/memories（content 必填，created_by=当前用户，后端处理）。 */
export function createMemory(data = {}) {
  return request({ url: `${MEMORY_BASE}`, method: 'POST', data }).then((res) => {
    const payload = (res && res.data) || {}
    return { code: 0, data: payload && typeof payload === 'object' ? payload : {}, message: 'success' }
  })
}

/** 删除：DELETE /api/memories/{id}（不存在 404，由拦截器统一提示 detail）。 */
export function deleteMemory(id) {
  return request({ url: `${MEMORY_BASE}/${id}`, method: 'DELETE' }).then((res) => {
    const payload = (res && res.data) || {}
    return { code: 0, data: payload && typeof payload === 'object' ? payload : { deleted: true }, message: 'success' }
  })
}
