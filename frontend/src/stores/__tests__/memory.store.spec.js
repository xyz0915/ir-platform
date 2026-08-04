/**
 * M5 记忆与 RAG Store 单元测试（加载 + 文档总量）。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

const api = vi.hoisted(() => ({
  memory: { listKnowledgeBases: vi.fn() },
}))
vi.mock('@/api/agent', () => ({ default: api }))

import { useMemoryStore } from '../memory'

describe('M5 Memory Store：加载 + 文档总量', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    api.memory.listKnowledgeBases.mockResolvedValue({
      code: 0,
      data: [
        { kb_id: 'kb1', doc_count: 100 },
        { kb_id: 'kb2', doc_count: 50 },
      ],
      message: 'ok',
    })
  })

  it('fetchKnowledgeBases 写入知识库并重置 loading', async () => {
    const store = useMemoryStore()
    const p = store.fetchKnowledgeBases()
    expect(store.loading).toBe(true)
    await p
    expect(store.loading).toBe(false)
    expect(store.knowledgeBases.length).toBe(2)
  })

  it('totalDocs 累加 doc_count', async () => {
    const store = useMemoryStore()
    await store.fetchKnowledgeBases()
    expect(store.totalDocs).toBe(150)
  })

  it('P0 真实结构：拆分 bases/stats/drafts', async () => {
    api.memory.listKnowledgeBases.mockResolvedValue({
      code: 0,
      data: {
        bases: [{ kb_id: 'ir_rules', name: '应急知识库(ir_rules)', doc_count: 42 }],
        stats: {
          collection: 'ir_rules',
          doc_count: 42,
          embedding_model: 'BAAI/bge-base-zh-v1.5',
          vector_store: 'Chroma',
          index_updated_at: '',
          approved_drafts: 3,
          collection_ready: true,
        },
        drafts: [
          { id: 1, title: '新增恶意软件', category: 'malware', severity: 'high', reviewed_at: '2026-08-01T00:00:00.000Z' },
        ],
      },
      message: 'ok',
    })
    const store = useMemoryStore()
    await store.fetchKnowledgeBases()
    expect(store.knowledgeBases.length).toBe(1)
    expect(store.knowledgeBases[0].kb_id).toBe('ir_rules')
    expect(store.stats.doc_count).toBe(42)
    expect(store.stats.collection_ready).toBe(true)
    expect(store.stats.approved_drafts).toBe(3)
    expect(store.drafts.length).toBe(1)
    expect(store.drafts[0].title).toBe('新增恶意软件')
    expect(store.vectorDocCount).toBe(42)
    expect(store.collectionReady).toBe(true)
  })
})
