/**
 * 记忆与 RAG Store（M5）。
 *
 * 职责：加载知识库 / 向量库概览（KnowledgeBase）+ 聚合统计（stats）+ 已批准草稿（drafts）。
 * P0 改造后真实后端（GET /api/knowledge/bases）返回：
 *   data.bases  → 真实向量库条目（ir_rules）
 *   data.stats  → { doc_count, embedding_model, vector_store, index_updated_at, approved_drafts, collection_ready }
 *   data.drafts → 已批准草稿精简列表
 *
 * 兼容：若后端/mock 返回数组（旧形态），则退化为旧行为（knowledgeBases=数组，
 * stats/drafts 为空），保证存量测试与 mock 路径不破坏。
 *
 * 设计依据：01-api-spec.md §5 / T9；记忆RAG审计报告 §5 P0。
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

  return {
    // state
    knowledgeBases,
    stats,
    drafts,
    loading,
    // getters
    totalDocs,
    vectorDocCount,
    collectionReady,
    // actions
    fetchKnowledgeBases,
  }
})
