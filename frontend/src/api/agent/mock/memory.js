/**
 * M5 记忆与 RAG Mock 适配器。
 *
 * 暴露：
 *   - listKnowledgeBases() 字段对齐 demo types/memory.ts 的 KnowledgeBase。
 *   - listMemories / searchMemories / createMemory / deleteMemory（P2 长期记忆
 *     agent_memories 空实现，返回同构信封保兼容；USE_MOCK.memory 默认 false，
 *     仅 vitest / mock 路径测试使用）。
 *
 * 设计依据：01-api-spec.md §5 / p2-design.md §5-§6。
 */
import { clone, delay, nowISO, ok } from './util'

/** 知识库 / 向量库（F3 长期记忆 / RAG），M5 轻量占位 */
const KNOWLEDGE_BASES = [
  { kb_id: 'kb-ioc', name: '历史 IOC 知识库', embedding_model: 'text-embedding-3-small', vector_store: 'Chroma', doc_count: 12840, updated_at: '2026-07-06T08:00:00.000Z' },
  { kb_id: 'kb-playbook', name: '处置 Playbook 库', embedding_model: 'bge-large-zh', vector_store: 'pgvector', doc_count: 312, updated_at: '2026-07-05T20:00:00.000Z' },
  { kb_id: 'kb-report', name: '复盘报告库', embedding_model: 'text-embedding-3-small', vector_store: 'Chroma', doc_count: 540, updated_at: '2026-07-04T18:00:00.000Z' },
]

export async function listKnowledgeBases() {
  await delay()
  return ok(clone(KNOWLEDGE_BASES))
}

/** P2 长期记忆：列表/筛选/分页（mock 空列表）。 */
export async function listMemories(params = {}) {
  await delay()
  const page = Number(params.page) || 1
  const page_size = Number(params.page_size) || 10
  return ok({ items: [], total: 0, page, page_size })
}

/** P2 长期记忆：关键词检索（mock 空列表）。 */
export async function searchMemories(q, params = {}) {
  await delay()
  void q
  void params
  return ok({ items: [], total: 0 })
}

/** P2 长期记忆：手动写入（mock 生成 id / created_at）。 */
export async function createMemory(data = {}) {
  await delay()
  const payload = data && typeof data === 'object' ? clone(data) : {}
  return ok({ id: Math.floor(Date.now() / 1000), created_at: nowISO(), ...payload })
}

/** P2 长期记忆：删除（mock 恒成功）。 */
export async function deleteMemory(id) {
  await delay()
  void id
  return ok({ deleted: true })
}
