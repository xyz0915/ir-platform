/**
 * 记忆与 RAG Store（M5）。
 *
 * 职责：加载知识库 / 向量库概览（KnowledgeBase）+ 聚合统计（stats）+ 已批准草稿（drafts）；
 * P2 新增长期记忆（agent_memories）状态与动作：memories 列表 / 检索 / 手动写入 / 删除。
 *
 * P0 改造后真实后端（GET /api/knowledge/bases）返回：
 *   data.bases  → 真实向量库条目（ir_rules）
 *   data.stats  → { doc_count, embedding_model, vector_store, index_updated_at, approved_drafts, collection_ready }
 *   data.drafts → 已批准草稿精简列表
 *
 * P2 长期记忆（p2-design.md §5）：
 *   GET    /api/memories        → data: { items, total, page, page_size }
 *   GET    /api/memories/search → data: { items, total }
 *   POST   /api/memories        → data: AgentMemory
 *   DELETE /api/memories/{id}   → data: { deleted: true }
 *
 * 兼容：若后端/mock 返回数组（旧形态），则退化为旧行为（knowledgeBases=数组，
 * stats/drafts 为空），保证存量测试与 mock 路径不破坏。
 *
 * 设计依据：01-api-spec.md §5 / T9；记忆RAG审计报告 §5 P0；p2-design.md §5-§6。
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import agentApi from '@/api/agent'

export const useMemoryStore = defineStore('memory', () => {
  // ===== 状态 =====
  const knowledgeBases = ref([]) // KnowledgeBase[]（真实向量库条目）
  const stats = ref({}) // 聚合统计 { doc_count, embedding_model, ... }
  const drafts = ref([]) // 已批准草稿精简列表
  const loading = ref(false)

  // ===== P2 长期记忆状态 =====
  const memories = ref([]) // AgentMemory[]
  const memoryTotal = ref(0)
  const memoryPage = ref(1)
  const memoryPageSize = ref(10)
  const memoryLoading = ref(false) // 列表加载
  const memorySearchLoading = ref(false) // 关键词检索
  const memoryMode = ref('list') // 'list' | 'search'（删除后按当前模式刷新）
  const memoryQuery = ref({ q: '', memory_type: '', agent_name: '', event_id: '' }) // 当前筛选

  // ===== 派生 =====
  const totalDocs = computed(() =>
    knowledgeBases.value.reduce((sum, kb) => sum + (Number(kb.doc_count) || 0), 0)
  )
  // 向量文档总数：优先 stats.doc_count（真实 collection 计数），回退到 bases 累加
  const vectorDocCount = computed(() => {
    const n = Number(stats.value && stats.value.doc_count)
    return Number.isFinite(n) && n > 0 ? n : totalDocs.value
  })
  // 索引状态：chroma collection 是否可用
  const collectionReady = computed(() => Boolean(stats.value && stats.value.collection_ready))

  // ===== 动作 =====
  async function fetchKnowledgeBases() {
    loading.value = true
    try {
      const res = await agentApi.memory.listKnowledgeBases()
      const payload = (res && res.data) || []
      // 兼容：real 返回 { bases, stats, drafts }；旧 mock / 旧后端返回数组
      if (Array.isArray(payload)) {
        knowledgeBases.value = payload
        stats.value = {}
        drafts.value = []
      } else {
        knowledgeBases.value = Array.isArray(payload.bases) ? payload.bases : []
        stats.value = payload.stats && typeof payload.stats === 'object' ? payload.stats : {}
        drafts.value = Array.isArray(payload.drafts) ? payload.drafts : []
      }
    } finally {
      loading.value = false
    }
  }

  // ── P2 长期记忆 ──

  /** 列表/筛选/分页：GET /api/memories。params 覆盖当前筛选（memoryQuery + 分页）。 */
  async function fetchMemories(params = {}) {
    memoryMode.value = 'list'
    memoryLoading.value = true
    try {
      const merged = {
        ...memoryQuery.value,
        page: memoryPage.value,
        page_size: memoryPageSize.value,
        ...params,
      }
      const res = await agentApi.memory.listMemories(merged)
      const data = (res && res.data) || {}
      memories.value = Array.isArray(data.items) ? data.items : []
      memoryTotal.value = Number(data.total) || 0
      if (data.page) memoryPage.value = Number(data.page) || 1
      if (data.page_size) memoryPageSize.value = Number(data.page_size) || 10
    } finally {
      memoryLoading.value = false
    }
  }

  /** 关键词检索：GET /api/memories/search?q=...。结果直接合并到列表展示。 */
  async function searchMemories(q, params = {}) {
    memoryMode.value = 'search'
    memorySearchLoading.value = true
    try {
      memoryQuery.value.q = q || ''
      const res = await agentApi.memory.searchMemories(q, params)
      const data = (res && res.data) || {}
      memories.value = Array.isArray(data.items) ? data.items : []
      memoryTotal.value = Number(data.total) || 0
    } finally {
      memorySearchLoading.value = false
    }
  }

  /** 手动写入：POST /api/memories。成功后按当前模式刷新列表。 */
  async function addMemory(payload = {}) {
    const res = await agentApi.memory.createMemory(payload)
    const row = (res && res.data) || {}
    await refreshMemories()
    return row
  }

  /** 删除：DELETE /api/memories/{id}。成功后按当前模式刷新列表。 */
  async function removeMemory(id) {
    const res = await agentApi.memory.deleteMemory(id)
    const data = (res && res.data) || {}
    await refreshMemories()
    return data
  }

  /** 按当前模式刷新：search 模式重跑关键词检索，否则拉列表（删除/写入后调用）。 */
  async function refreshMemories() {
    if (memoryMode.value === 'search') {
      await searchMemories(memoryQuery.value.q || '', {
        memory_type: memoryQuery.value.memory_type || undefined,
        agent_name: memoryQuery.value.agent_name || undefined,
        event_id: memoryQuery.value.event_id || undefined,
      })
    } else {
      await fetchMemories({
        memory_type: memoryQuery.value.memory_type || undefined,
        agent_name: memoryQuery.value.agent_name || undefined,
        event_id: memoryQuery.value.event_id || undefined,
      })
    }
  }

  return {
    // state
    knowledgeBases,
    stats,
    drafts,
    loading,
    // P2 长期记忆 state
    memories,
    memoryTotal,
    memoryPage,
    memoryPageSize,
    memoryLoading,
    memorySearchLoading,
    memoryMode,
    memoryQuery,
    // getters
    totalDocs,
    vectorDocCount,
    collectionReady,
    // actions
    fetchKnowledgeBases,
    // P2 长期记忆 actions
    fetchMemories,
    searchMemories,
    addMemory,
    removeMemory,
    refreshMemories,
  }
})
