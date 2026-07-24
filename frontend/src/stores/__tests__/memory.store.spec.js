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
})
