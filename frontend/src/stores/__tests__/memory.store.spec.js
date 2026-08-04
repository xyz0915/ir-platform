/**
 * M5 记忆与 RAG Store 单元测试（加载 + 文档总量 + P2 长期记忆动作）。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

const api = vi.hoisted(() => ({
  memory: {
    listKnowledgeBases: vi.fn(),
    listMemories: vi.fn(),
    searchMemories: vi.fn(),
    createMemory: vi.fn(),
    deleteMemory: vi.fn(),
  },
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

describe('M5 Memory Store：P2 长期记忆动作', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    api.memory.listMemories.mockResolvedValue({
      code: 0,
      data: {
        items: [
          { id: 1, agent_name: 'root_cause', memory_type: 'conclusion', content: '根因是 powershell C2', source_node: 'root_cause', event_id: 'evt-1', host_id: 3, created_by: 'system', created_at: '2026-08-04 08:00:00' },
        ],
        total: 1,
        page: 1,
        page_size: 10,
      },
      message: 'ok',
    })
    api.memory.searchMemories.mockResolvedValue({
      code: 0,
      data: { items: [{ id: 2, agent_name: 'responder', memory_type: 'disposition', content: '已隔离主机', created_by: 'admin', created_at: '2026-08-04 09:00:00' }], total: 1 },
      message: 'ok',
    })
    api.memory.createMemory.mockResolvedValue({
      code: 0,
      data: { id: 9, agent_name: 'manual', memory_type: 'summary', content: '手动记忆', created_by: 'admin', created_at: '2026-08-04 10:00:00' },
      message: 'ok',
    })
    api.memory.deleteMemory.mockResolvedValue({ code: 0, data: { deleted: true }, message: 'ok' })
  })

  it('fetchMemories 写入列表 + total 并重置 loading', async () => {
    const store = useMemoryStore()
    const p = store.fetchMemories()
    expect(store.memoryLoading).toBe(true)
    await p
    expect(store.memoryLoading).toBe(false)
    expect(store.memories.length).toBe(1)
    expect(store.memoryTotal).toBe(1)
    expect(store.memoryMode).toBe('list')
    expect(api.memory.listMemories).toHaveBeenCalled()
  })

  it('searchMemories 写入检索结果并置 search 模式', async () => {
    const store = useMemoryStore()
    await store.searchMemories('powershell', { memory_type: 'conclusion' })
    expect(store.memoryMode).toBe('search')
    expect(store.memoryQuery.q).toBe('powershell')
    expect(store.memories[0].agent_name).toBe('responder')
    expect(store.memoryTotal).toBe(1)
    expect(api.memory.searchMemories).toHaveBeenCalledWith('powershell', { memory_type: 'conclusion' })
  })

  it('addMemory 调 createMemory 并刷新列表（list 模式）', async () => {
    const store = useMemoryStore()
    const row = await store.addMemory({ content: '手动记忆', memory_type: 'summary' })
    expect(row.id).toBe(9)
    expect(api.memory.createMemory).toHaveBeenCalledWith({ content: '手动记忆', memory_type: 'summary' })
    // list 模式刷新 → 重新拉列表
    expect(api.memory.listMemories).toHaveBeenCalled()
  })

  it('removeMemory 调 deleteMemory 并刷新列表（search 模式重跑检索）', async () => {
    const store = useMemoryStore()
    await store.searchMemories('powershell')
    vi.clearAllMocks()
    const data = await store.removeMemory(2)
    expect(data.deleted).toBe(true)
    expect(api.memory.deleteMemory).toHaveBeenCalledWith(2)
    // search 模式刷新 → 重跑关键词检索
    expect(api.memory.searchMemories).toHaveBeenCalled()
  })
})
