/**
 * M5 记忆与 RAG Mock 适配器。
 *
 * 暴露：listKnowledgeBases()
 * 字段对齐 demo types/memory.ts 的 KnowledgeBase。
 *
 * 设计依据：01-api-spec.md §5。
 */
import { clone, delay, ok } from './util'

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
